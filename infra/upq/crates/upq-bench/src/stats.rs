#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LatencySummary {
    pub p50_ms: f64,
    pub p95_ms: f64,
    pub p99_ms: f64,
    pub throughput_qps: f64,
}

pub fn summarize(latencies_ms: &[f64], total_elapsed_ms: f64) -> LatencySummary {
    let mut ordered = latencies_ms.to_vec();
    ordered.sort_by(f64::total_cmp);

    let count = ordered.len() as f64;
    let throughput_qps = if total_elapsed_ms <= 0.0 {
        0.0
    } else {
        count / (total_elapsed_ms / 1000.0)
    };

    LatencySummary {
        p50_ms: percentile(&ordered, 0.50),
        p95_ms: percentile(&ordered, 0.95),
        p99_ms: percentile(&ordered, 0.99),
        throughput_qps,
    }
}

fn percentile(sorted_values: &[f64], p: f64) -> f64 {
    if sorted_values.is_empty() {
        return 0.0;
    }
    let rank = ((sorted_values.len() as f64 * p).ceil() as usize).saturating_sub(1);
    sorted_values[rank.min(sorted_values.len() - 1)]
}

#[cfg(test)]
mod tests {
    use super::{summarize, LatencySummary};

    #[test]
    fn summarize_calculates_percentiles_and_throughput() {
        let summary = summarize(&[10.0, 20.0, 30.0, 40.0, 50.0], 200.0);
        assert_eq!(
            summary,
            LatencySummary {
                p50_ms: 30.0,
                p95_ms: 50.0,
                p99_ms: 50.0,
                throughput_qps: 25.0,
            }
        );
    }

    #[test]
    fn summarize_handles_empty_inputs() {
        let summary = summarize(&[], 0.0);
        assert_eq!(
            summary,
            LatencySummary {
                p50_ms: 0.0,
                p95_ms: 0.0,
                p99_ms: 0.0,
                throughput_qps: 0.0,
            }
        );
    }
}
