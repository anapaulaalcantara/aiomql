import asyncio
import logging

from .tracker import Tracker
from ..traders import SimpleTrader
from ...symbol import Symbol
from ...trader import Trader
from ...candle import Candles
from ...strategy import Strategy
from ...core import TimeFrame, OrderType
from ...sessions import Sessions

logger = logging.getLogger(__name__)


class FingerTrap(Strategy):
    ttf: TimeFrame
    etf: TimeFrame
    trend: int
    fast_ema: int
    slow_ema: int
    entry_ema: int
    parameters: dict
    ecc: int
    tcc: int
    trader: Trader
    tracker: Tracker
    parameters = {"trend": 3, "fast_ema": 8, "slow_ema": 20, "etf": TimeFrame.M5,
                  "ttf": TimeFrame.H1, "entry_ema": 5, "tcc": 50, "ecc": 600}

    def __init__(self, *, symbol: Symbol, params: dict | None = None, trader: Trader = None, sessions: Sessions = None,
                 name: str = 'FingerTrap'):
        super().__init__(symbol=symbol, params=params, sessions=sessions, name=name)
        self.trader = trader or SimpleTrader(symbol=self.symbol)
        self.tracker: Tracker = Tracker(snooze=self.ttf.time)

    async def check_trend(self):
        try:
            candles: Candles = await self.symbol.copy_rates_from_pos(timeframe=self.ttf, count=self.tcc)
            if not ((current := candles[-1].time) >= self.tracker.trend_time):
                self.tracker.update(new=False, order_type=None)
                return
            self.tracker.update(new=True, trend_time=current)
            candles.ta.ema(length=self.slow_ema, append=True, fillna=0)
            candles.ta.ema(length=self.fast_ema, append=True, fillna=0)
            candles.rename(inplace=True, **{f"EMA_{self.fast_ema}": "fast", f"EMA_{self.slow_ema}": "slow"})

            fas = candles.ta_lib.above(candles.fast, candles.slow) # fast above slow
            fbs = candles.ta_lib.below(candles.fast, candles.slow) # fast below slow
            caf = candles.ta_lib.above(candles.close, candles.fast) # close above fast
            cbf = candles.ta_lib.below(candles.close, candles.fast) # close below fast
            current = candles[-2]
            if fas.iloc[-1] and caf.iloc[-1] and current.is_bullish():
                self.tracker.update(trend="bullish")

            elif fbs.iloc[-1] and cbf.iloc[-1] and current.is_bearish():
                self.tracker.update(trend="bearish")
            else:
                self.tracker.update(trend="ranging", snooze=self.ttf.time, order_type=None)
        except Exception as err:
            logger.error(f"{err} for {self.symbol} in {self.__class__.__name__}.check_trend")
            self.tracker.update(snooze=self.ttf.time, order_type=None)

    async def confirm_trend(self):
        try:
            candles = await self.symbol.copy_rates_from_pos(timeframe=self.etf, count=self.ecc)
            if not ((current := candles[-1].time) >= self.tracker.entry_time):
                self.tracker.update(new=False, order_type=None)
                return

            self.tracker.update(new=True, entry_time=current)
            candles.ta.ema(length=self.entry_ema, append=True)
            candles.rename(**{f"EMA_{self.entry_ema}": "ema"})
            cae = candles.ta_lib.cross(candles.close, candles.ema)
            cbe = candles.ta_lib.cross(candles.close, candles.ema, above=False)
            if self.tracker.bullish and any([cae.iloc[-1], cae.iloc[-2]]):
                self.tracker.update(snooze=self.ttf.time, order_type=OrderType.BUY)
            elif self.tracker.bearish and any([cbe.iloc[-1], cbe.iloc[-2]]):
                self.tracker.update(snooze=self.ttf.time, order_type=OrderType.SELL)
            else:
                self.tracker.update(snooze=self.etf.time, order_type=None)
        except Exception as err:
            logger.error(f"{err} for {self.symbol} in {self.__class__.__name__}.confirm_trend\n")
            self.tracker.update(snooze=self.etf.time, order_type=None)

    async def watch_market(self):
        await self.check_trend()
        if not self.tracker.ranging:
            await self.confirm_trend()

    async def trade(self):
        logger.info(f"Trading {self.symbol}")
        async with self.sessions as sess:
            await self.sleep(self.ttf.time)
            while True:
                await sess.check()
                try:
                    await self.watch_market()
                    if not self.tracker.new:
                        await asyncio.sleep(2)
                        continue
                    if self.tracker.order_type is None:
                        await self.sleep(self.tracker.snooze)
                        continue
                    await self.trader.place_trade(order_type=self.tracker.order_type, parameters=self.parameters)
                    await self.sleep(self.tracker.snooze)
                except Exception as err:
                    logger.error(f"{err} For {self.symbol} in {self.__class__.__name__}.trade\n")
                    await self.sleep(self.ttf.time)