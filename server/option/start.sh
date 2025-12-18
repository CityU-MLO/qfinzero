mkdir -p logs

nohup uvicorn daily_backtest:app --host 0.0.0.0 --port 19747 --reload \
  > logs/daily_backtest.out 2>&1 & echo $! > logs/daily_backtest.pid

nohup uvicorn app:app --host 0.0.0.0 --port 19787 --reload \
  > logs/app.out 2>&1 & echo $! > logs/app.pid
