//! Push-to-talk microphone capture (cpal) → 16 kHz mono 16-bit WAV in memory.
//!
//! cpal streams are not `Send` on every platform, so each recording owns its stream on a
//! dedicated thread; `start` returns a handle whose `stop` yields the WAV bytes.

use std::io::Cursor;
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{SampleFormat, SizedSample};

pub const TARGET_RATE: u32 = 16_000;
/// Hard cap so a stuck key can't record forever.
pub const MAX_SECONDS: u32 = 60;
/// Below this level the clip is treated as silence (mic muted / nothing said).
const SILENCE_RMS: f32 = 0.0015;

pub struct Recording {
    stop_tx: mpsc::Sender<()>,
    done_rx: mpsc::Receiver<Result<(Vec<f32>, u32), String>>,
}

impl Recording {
    /// Starts recording from the default input device.
    pub fn start() -> Result<Recording, String> {
        let (stop_tx, stop_rx) = mpsc::channel::<()>();
        let (done_tx, done_rx) = mpsc::channel();
        let (ready_tx, ready_rx) = mpsc::channel::<Result<(), String>>();
        thread::Builder::new()
            .name("nudgy-mic".into())
            .spawn(move || {
                let samples = Arc::new(Mutex::new(Vec::<f32>::new()));
                let stream = match open_stream(samples.clone()) {
                    Ok(s) => s,
                    Err(e) => {
                        let _ = ready_tx.send(Err(e));
                        return;
                    }
                };
                let _ = ready_tx.send(Ok(()));
                let _ = stop_rx.recv_timeout(Duration::from_secs(MAX_SECONDS as u64));
                let rate = stream.1;
                drop(stream.0); // stops capture
                let data = std::mem::take(&mut *samples.lock().unwrap());
                let _ = done_tx.send(Ok((data, rate)));
            })
            .map_err(|e| e.to_string())?;
        ready_rx
            .recv()
            .map_err(|_| "microphone thread died".to_string())??;
        Ok(Recording { stop_tx, done_rx })
    }

    /// Stops and returns a 16 kHz mono WAV, or `Ok(None)` if nothing but silence was heard.
    pub fn stop(self) -> Result<Option<Vec<u8>>, String> {
        let _ = self.stop_tx.send(());
        let (samples, rate) = self
            .done_rx
            .recv_timeout(Duration::from_secs(3))
            .map_err(|_| "microphone did not stop".to_string())??;
        if rms(&samples) < SILENCE_RMS {
            return Ok(None);
        }
        encode_wav(&resample(&samples, rate, TARGET_RATE)).map(Some)
    }

    /// Stops and discards (a short tap, or cancelled).
    pub fn cancel(self) {
        let _ = self.stop_tx.send(());
    }
}

fn open_stream(buf: Arc<Mutex<Vec<f32>>>) -> Result<(cpal::Stream, u32), String> {
    let host = cpal::default_host();
    let device = host.default_input_device().ok_or("no microphone found")?;
    let supported = device
        .default_input_config()
        .map_err(|e| format!("microphone config: {e}"))?;
    let rate = supported.sample_rate();
    let channels = supported.channels() as usize;
    let config = supported.config();
    let max_samples = (rate * MAX_SECONDS) as usize;
    let stream = match supported.sample_format() {
        SampleFormat::F32 => build::<f32>(&device, &config, channels, max_samples, buf, |s| s),
        SampleFormat::I16 => build::<i16>(&device, &config, channels, max_samples, buf, |s| {
            s as f32 / i16::MAX as f32
        }),
        SampleFormat::U16 => build::<u16>(&device, &config, channels, max_samples, buf, |s| {
            (s as f32 - 32768.0) / 32768.0
        }),
        SampleFormat::I32 => build::<i32>(&device, &config, channels, max_samples, buf, |s| {
            s as f32 / i32::MAX as f32
        }),
        other => return Err(format!("unsupported microphone sample format {other:?}")),
    }?;
    stream
        .play()
        .map_err(|e| format!("start microphone: {e}"))?;
    Ok((stream, rate))
}

fn build<T: SizedSample + Copy + Send + 'static>(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    channels: usize,
    max_samples: usize,
    buf: Arc<Mutex<Vec<f32>>>,
    to_f32: fn(T) -> f32,
) -> Result<cpal::Stream, String> {
    device
        .build_input_stream(
            config,
            move |data: &[T], _: &cpal::InputCallbackInfo| {
                let mut out = buf.lock().unwrap();
                for frame in data.chunks(channels.max(1)) {
                    if out.len() >= max_samples {
                        return;
                    }
                    let sum: f32 = frame.iter().map(|&s| to_f32(s)).sum();
                    out.push(sum / frame.len() as f32);
                }
            },
            |e| log::error!("microphone stream error: {e}"),
            None,
        )
        .map_err(|e| format!("open microphone: {e}"))
}

/// Linear-interpolation resampler; plenty for speech going to an STT model.
pub fn resample(input: &[f32], from: u32, to: u32) -> Vec<f32> {
    if from == to || input.is_empty() {
        return input.to_vec();
    }
    let ratio = from as f64 / to as f64;
    let out_len = ((input.len() as f64) / ratio).floor() as usize;
    (0..out_len)
        .map(|i| {
            let pos = i as f64 * ratio;
            let i0 = pos.floor() as usize;
            let i1 = (i0 + 1).min(input.len() - 1);
            let frac = (pos - i0 as f64) as f32;
            input[i0] * (1.0 - frac) + input[i1] * frac
        })
        .collect()
}

pub fn encode_wav(samples: &[f32]) -> Result<Vec<u8>, String> {
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: TARGET_RATE,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut cursor = Cursor::new(Vec::new());
    {
        let mut w = hound::WavWriter::new(&mut cursor, spec).map_err(|e| e.to_string())?;
        for &s in samples {
            w.write_sample((s.clamp(-1.0, 1.0) * i16::MAX as f32) as i16)
                .map_err(|e| e.to_string())?;
        }
        w.finalize().map_err(|e| e.to_string())?;
    }
    Ok(cursor.into_inner())
}

/// Root-mean-square level, used to skip sending pure silence.
pub fn rms(samples: &[f32]) -> f32 {
    if samples.is_empty() {
        return 0.0;
    }
    (samples.iter().map(|s| s * s).sum::<f32>() / samples.len() as f32).sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resample_48k_to_16k_keeps_duration() {
        let one_second: Vec<f32> = (0..48_000).map(|i| (i as f32 * 0.01).sin()).collect();
        let out = resample(&one_second, 48_000, 16_000);
        assert_eq!(out.len(), 16_000);
        assert!((out[100] - one_second[300]).abs() < 1e-6);
    }

    #[test]
    fn resample_44k1_is_close() {
        let input = vec![0.5; 44_100];
        let out = resample(&input, 44_100, 16_000);
        assert!((out.len() as i64 - 16_000).abs() <= 1);
        assert!(out.iter().all(|s| (s - 0.5).abs() < 1e-6));
    }

    #[test]
    fn wav_header_and_length() {
        let wav = encode_wav(&vec![0.0; 1600]).unwrap();
        assert_eq!(&wav[..4], b"RIFF");
        assert_eq!(&wav[8..12], b"WAVE");
        assert_eq!(wav.len(), 44 + 1600 * 2);
        let reader = hound::WavReader::new(Cursor::new(wav)).unwrap();
        assert_eq!(reader.spec().sample_rate, TARGET_RATE);
    }

    #[test]
    fn wav_clamps_out_of_range() {
        let wav = encode_wav(&[2.0, -2.0]).unwrap();
        let mut r = hound::WavReader::new(Cursor::new(wav)).unwrap();
        let s: Vec<i16> = r.samples::<i16>().map(Result::unwrap).collect();
        assert_eq!(s, vec![i16::MAX, -i16::MAX]);
    }

    #[test]
    fn rms_of_silence_and_tone() {
        assert_eq!(rms(&[]), 0.0);
        assert!(rms(&[0.0; 100]) < 1e-6);
        assert!(rms(&[0.5, -0.5, 0.5, -0.5]) > 0.49);
    }
}
