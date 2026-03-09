use serde_json::Value;

/// A parsed indicator request.
#[derive(Debug, Clone, PartialEq)]
pub enum Indicator {
    Ma(usize),
    Ema(usize),
    Macd,
}

/// Parse the `indicators` query param CSV string into validated Indicator list.
pub fn parse_indicators(csv: &str) -> Result<Vec<Indicator>, String> {
    let mut seen = std::collections::HashSet::new();
    let mut result = Vec::new();

    for raw in csv.split(',') {
        let token = raw.trim().to_lowercase();
        if token.is_empty() {
            continue;
        }
        if !seen.insert(token.clone()) {
            continue;
        }

        if token == "macd" {
            result.push(Indicator::Macd);
        } else if let Some(suffix) = token.strip_prefix("ma_") {
            let n: usize = suffix
                .parse()
                .map_err(|_| format!("invalid indicator: '{raw}' — expected ma_N where N is a positive integer"))?;
            if n == 0 {
                return Err(format!("invalid indicator: '{raw}' — window must be > 0"));
            }
            result.push(Indicator::Ma(n));
        } else if let Some(suffix) = token.strip_prefix("ema_") {
            let n: usize = suffix
                .parse()
                .map_err(|_| format!("invalid indicator: '{raw}' — expected ema_N where N is a positive integer"))?;
            if n == 0 {
                return Err(format!("invalid indicator: '{raw}' — window must be > 0"));
            }
            result.push(Indicator::Ema(n));
        } else {
            return Err(format!(
                "unknown indicator: '{raw}'. Supported: ma_N, ema_N, macd"
            ));
        }
    }

    Ok(result)
}

/// Compute the maximum lookback (number of extra trading days) needed.
pub fn max_lookback(indicators: &[Indicator]) -> usize {
    let mut max = 0usize;
    for ind in indicators {
        let need = match ind {
            Indicator::Ma(n) => *n - 1,
            Indicator::Ema(n) => *n * 2,
            Indicator::Macd => 70,
        };
        if need > max {
            max = need;
        }
    }
    max
}

/// Compute all requested indicators on the rows in-place.
///
/// Rows must be sorted by (ticker, date) and have `close` and `ticker` fields.
pub fn compute_indicators(rows: &mut [Value], indicators: &[Indicator]) {
    if indicators.is_empty() || rows.is_empty() {
        return;
    }

    let groups = group_by_ticker(rows);

    for (_ticker, indices) in &groups {
        let closes: Vec<Option<f64>> = indices
            .iter()
            .map(|&i| rows[i].get("close").and_then(|v| v.as_f64()))
            .collect();

        for ind in indicators {
            match ind {
                Indicator::Ma(n) => {
                    let values = compute_sma(&closes, *n);
                    let key = format!("ma_{n}");
                    for (j, &idx) in indices.iter().enumerate() {
                        if let Some(obj) = rows[idx].as_object_mut() {
                            obj.insert(
                                key.clone(),
                                match values[j] {
                                    Some(v) => Value::from(round6(v)),
                                    None => Value::Null,
                                },
                            );
                        }
                    }
                }
                Indicator::Ema(n) => {
                    let values = compute_ema(&closes, *n);
                    let key = format!("ema_{n}");
                    for (j, &idx) in indices.iter().enumerate() {
                        if let Some(obj) = rows[idx].as_object_mut() {
                            obj.insert(
                                key.clone(),
                                match values[j] {
                                    Some(v) => Value::from(round6(v)),
                                    None => Value::Null,
                                },
                            );
                        }
                    }
                }
                Indicator::Macd => {
                    let (macd_line, signal, histogram) = compute_macd(&closes);
                    for (j, &idx) in indices.iter().enumerate() {
                        if let Some(obj) = rows[idx].as_object_mut() {
                            obj.insert("macd".to_string(), opt_f64_value(macd_line[j]));
                            obj.insert("macd_signal".to_string(), opt_f64_value(signal[j]));
                            obj.insert("macd_histogram".to_string(), opt_f64_value(histogram[j]));
                        }
                    }
                }
            }
        }
    }
}

fn round6(v: f64) -> f64 {
    (v * 1_000_000.0).round() / 1_000_000.0
}

fn opt_f64_value(v: Option<f64>) -> Value {
    match v {
        Some(x) => Value::from(round6(x)),
        None => Value::Null,
    }
}

fn group_by_ticker(rows: &[Value]) -> Vec<(String, Vec<usize>)> {
    let mut groups: Vec<(String, Vec<usize>)> = Vec::new();
    for (i, row) in rows.iter().enumerate() {
        let ticker = row
            .get("ticker")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if let Some(last) = groups.last_mut() {
            if last.0 == ticker {
                last.1.push(i);
                continue;
            }
        }
        groups.push((ticker, vec![i]));
    }
    groups
}

fn compute_sma(closes: &[Option<f64>], window: usize) -> Vec<Option<f64>> {
    let n = closes.len();
    let mut result = vec![None; n];

    for i in (window - 1)..n {
        let mut sum = 0.0;
        let mut valid = true;
        for j in (i + 1 - window)..=i {
            match closes[j] {
                Some(v) => sum += v,
                None => {
                    valid = false;
                    break;
                }
            }
        }
        if valid {
            result[i] = Some(sum / window as f64);
        }
    }
    result
}

fn compute_ema(closes: &[Option<f64>], window: usize) -> Vec<Option<f64>> {
    let n = closes.len();
    let mut result = vec![None; n];
    let multiplier = 2.0 / (window as f64 + 1.0);

    let seed_sma = compute_sma(closes, window);

    let mut ema_prev: Option<f64> = None;
    for i in 0..n {
        if ema_prev.is_none() {
            if let Some(sma) = seed_sma[i] {
                ema_prev = Some(sma);
                result[i] = ema_prev;
            }
        } else if let Some(close) = closes[i] {
            let prev = ema_prev.unwrap();
            let ema = close * multiplier + prev * (1.0 - multiplier);
            ema_prev = Some(ema);
            result[i] = Some(ema);
        }
    }
    result
}

fn compute_macd(closes: &[Option<f64>]) -> (Vec<Option<f64>>, Vec<Option<f64>>, Vec<Option<f64>>) {
    let n = closes.len();
    let ema_fast = compute_ema(closes, 12);
    let ema_slow = compute_ema(closes, 26);

    let mut macd_line: Vec<Option<f64>> = vec![None; n];
    for i in 0..n {
        if let (Some(fast), Some(slow)) = (ema_fast[i], ema_slow[i]) {
            macd_line[i] = Some(fast - slow);
        }
    }

    let signal = compute_ema(&macd_line, 9);

    let mut histogram: Vec<Option<f64>> = vec![None; n];
    for i in 0..n {
        if let (Some(m), Some(s)) = (macd_line[i], signal[i]) {
            histogram[i] = Some(m - s);
        }
    }

    (macd_line, signal, histogram)
}
