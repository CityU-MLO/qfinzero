"""QFinZero agent benchmark (``qfz-bench``) on the synthetic sample.

    qfz-sample generate --out ./qfz-sample
    QFZ_DATA_ROOT=./qfz-sample qfz-server                 # the stack on the sample
    qfz-bench oracle --hub http://127.0.0.1:19777 --api-key qfz_…   # platform check
    qfz-bench run --hub … --api-key … --model gpt-4.1 --out runs/gpt41.jsonl

Tasks (``data/tasks-v1.0.jsonl``) cover daily and intraday data, quotes,
options, events, corporate actions, time-locked questions and trading
episodes. See docs/en/bench.md.
"""

from .tasks import BENCH_VERSION, Task, build_tasks, load_tasks

__all__ = ["BENCH_VERSION", "Task", "build_tasks", "load_tasks"]
