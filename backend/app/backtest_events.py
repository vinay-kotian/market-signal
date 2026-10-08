"""Audit shared-service transitions without reproducing their decision logic."""
import json
from datetime import datetime

from app.database import connect
from app.trade_repository import TradeRepository


class BacktestTimeline:
    def __init__(self, path, run_id, clock):
        self.path, self.run_id, self.clock = path, run_id, clock
        self.signals_seen = self.selections_seen = self.trade_events_seen = 0
        self.previous_levels = {}
        self.previous_trades = {}
        self.entry_results_seen = {}
        self.deadlines_seen = set()
        self.spot = None
        with connect(path) as connection:
            connection.execute('''CREATE TABLE backtest_events (
                id INTEGER PRIMARY KEY, backtest_run_id TEXT NOT NULL,
                trade_id INTEGER, signal_id INTEGER, timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL, payload TEXT NOT NULL)''')

    def record(self, event_type, payload=None, *, trade_id=None, signal_id=None, timestamp=None, connection=None):
        values = (self.run_id, trade_id, signal_id, (timestamp or self.clock()).isoformat(),
                  event_type, json.dumps(payload or {}, default=str))
        sql = '''INSERT INTO backtest_events
            (backtest_run_id, trade_id, signal_id, timestamp, event_type, payload)
            VALUES (?, ?, ?, ?, ?, ?)'''
        if connection is not None:
            connection.execute(sql, values)
        else:
            with connect(self.path) as connection:
                connection.execute(sql, values)

    def capture(self, tick=None, monitor=None):
        trades = TradeRepository(self.path, mode='BACKTEST').recent(100000)
        trade_map = {trade.trade_id: trade for trade in trades}
        with connect(self.path) as connection:
            levels = connection.execute('SELECT * FROM levels ORDER BY id').fetchall()
            for row in levels:
                previous = self.previous_levels.get(row['id'])
                payload = dict(level_id=row['id'], level=row['price'], instrument=row['instrument'],
                               index_price=self.spot, status=row['status'], armed_from=row['armed_from'])
                if tick and tick.instrument == row['instrument']:
                    self.record('LEVEL_OBSERVED', payload, connection=connection)
                if row['status'] == 'ACTIVE' and previous != 'ACTIVE':
                    self.record('LEVEL_ARMED', payload, connection=connection)
                self.previous_levels[row['id']] = row['status']
            signals = connection.execute('SELECT * FROM signals WHERE id > ? ORDER BY id',
                                         (self.signals_seen,)).fetchall()
            for row in signals:
                payload = dict(row)
                payload['index_price'] = payload['trigger_price']
                # Shared monitor already decided whether a valid touch/cross occurred.
                trigger = next((event for event in monitor.recent_events()
                                if event.id == row['trigger_id']), None) if monitor else None
                if trigger:
                    self.record('LEVEL_TOUCH' if trigger.current_price == trigger.level_price else 'LEVEL_CROSS',
                                payload, signal_id=row['id'], connection=connection)
                self.record('SIGNAL_CREATED', payload, signal_id=row['id'], connection=connection)
                self.signals_seen = row['id']
            selections = connection.execute('SELECT * FROM option_selections WHERE id > ? ORDER BY id',
                                            (self.selections_seen,)).fetchall()
            for row in selections:
                payload = dict(row)
                contract = connection.execute('SELECT payload FROM backtest_contracts WHERE symbol = ?',
                                              (row['option_symbol'],)).fetchone()
                if contract:
                    payload.update(json.loads(contract['payload']))
                self.record('OPTION_SELECTED' if row['status'] == 'SELECTED' else 'OPTION_SELECTION_FAILED',
                            payload, signal_id=row['signal_id'], connection=connection)
                self.selections_seen = row['id']
            for row in connection.execute('SELECT * FROM trade_entry_results ORDER BY option_selection_id').fetchall():
                identity = row['option_selection_id']
                state = (row['status'], row['failure_reason'])
                if row['status'] == 'FAILED' and self.entry_results_seen.get(identity) != state:
                    selection = connection.execute('SELECT signal_id FROM option_selections WHERE id = ?',
                                                   (identity,)).fetchone()
                    self.record('ENTRY_REJECTED', dict(row), signal_id=selection['signal_id'],
                                timestamp=datetime.fromisoformat(row['timestamp']), connection=connection)
                self.entry_results_seen[identity] = state
            events = connection.execute('SELECT * FROM trade_events WHERE id > ? ORDER BY id',
                                        (self.trade_events_seen,)).fetchall()
            types = {'POSITION_OPENED': 'TRADE_ENTERED', 'STOP_LOSS_HIT': 'EXIT_TRIGGERED',
                     'POSITION_CLOSED': 'TRADE_EXITED', 'MARKET_CLOSING_EXIT_TRIGGERED': 'EXIT_TRIGGERED',
                     'BREAKEVEN_PROTECTION_ACTIVATED': 'BREAKEVEN_ACTIVATED',
                     'PROFIT_LOCK_ACTIVATED': 'BREAKEVEN_ACTIVATED',
                     'TRAILING_STOP_UPDATED': 'TRAILING_UPDATED', 'TRAILING_STEP_CHANGED': 'TRAILING_STEP_CHANGED'}
            for row in events:
                trade = trade_map[row['trade_id']]
                payload = {**trade.model_dump(mode='json'), **dict(row),
                           'level': trade.trigger_level, 'index_price': self.spot,
                           'option_price': row['price'], 'reason': trade.exit_reason,
                           'return_percent': (row['price'] / trade.entry_price - 1) * 100}
                # Keep event-time protection metadata; final values live on the trade.
                previous = self.previous_trades.get(trade.trade_id)
                payload['highest_price'] = row['highest_price'] or max(
                    trade.entry_price, row['price'], previous.highest_price if previous else trade.entry_price)
                payload['stop_price'] = row['current_stop'] or (
                    previous.current_stop_loss if previous else trade.initial_stop_loss)
                if row['event_type'] == 'POSITION_OPENED':
                    payload['highest_price'] = trade.entry_price
                    payload['stop_price'] = trade.initial_stop_loss
                    payload['status'] = 'OPEN'
                    for key in ('exit_price', 'exit_time', 'exit_reason', 'realised_pnl', 'realised_pnl_percentage'):
                        payload[key] = None
                self.record(types[row['event_type']], payload, trade_id=trade.trade_id,
                            signal_id=trade.signal_id, timestamp=datetime.fromisoformat(row['timestamp']),
                            connection=connection)
                if row['current_stop'] is not None and row['current_stop'] != row['previous_stop']:
                    self.record('STOP_UPDATED', payload, trade_id=trade.trade_id,
                                signal_id=trade.signal_id, connection=connection)
                self.trade_events_seen = row['id']
            for trade in trades:
                connection.execute('UPDATE backtest_events SET trade_id = ? WHERE signal_id = ? AND trade_id IS NULL',
                                   (trade.trade_id, trade.signal_id))
            self.previous_trades = trade_map

    def deadlines(self, trades, rules, until):
        with connect(self.path) as connection:
            for trade in trades.all_open(connection):
                deadline = rules.exit_deadline(trade)
                if deadline <= until and trade.trade_id not in self.deadlines_seen:
                    self.record('MANDATORY_EXIT', dict(option_symbol=trade.option_symbol,
                        level=trade.trigger_level, reason='Awaiting first option quote at or after deadline'),
                        trade_id=trade.trade_id, timestamp=deadline, connection=connection)
                    self.deadlines_seen.add(trade.trade_id)

    def list(self):
        with connect(self.path) as connection:
            return [{**dict(row), 'payload': json.loads(row['payload'])} for row in connection.execute(
                'SELECT * FROM backtest_events ORDER BY julianday(timestamp), id')]
