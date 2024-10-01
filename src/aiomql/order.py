from logging import getLogger

from .core.models import TradeRequest, TradeOrder
from .core.constants import TradeAction, OrderTime, OrderFilling
from .core.exceptions import OrderError
from .utils import backoff_decorator, error_handler
from MetaTrader5 import OrderCheckResult, OrderSendResult

logger = getLogger(__name__)


class Order(TradeRequest):
    """Trade order related functions and properties. Subclass of TradeRequest."""

    def __init__(self, **kwargs):
        """Initialize the order object with keyword arguments, symbol must be provided.
        Provide default values for action, type_time and type_filling if not provided.

        Args:
            **kwargs: Keyword arguments must match the attributes of TradeRequest as well as the attributes of
             Order class as specified in the annotations in the class definition.

        Default Values:
            action (TradeAction.DEAL): Trade action
            type_time (OrderTime.DAY): Order time
            type_filling (OrderFilling.FOK): Order filling
        """
        kwargs = {'action': TradeAction.DEAL, OrderTime.DAY: self.type_time, 'type_filling': OrderFilling.FOK, **kwargs}
        super().__init__(**kwargs)

    async def orders_total(self):
        """Get the number of active pending orders.

        Returns:
            (int): total number of active orders
        """
        return await self.mt5.orders_total()

    async def get_order(self, *, ticket: int) -> TradeOrder | None:
        """
        Get a pending order by ticket number.

        Args:
            ticket (int): Order ticket number

        Returns:
        """
        orders = await self.mt5.orders_get(ticket=ticket)
        order = None
        for order_ in orders:
            if order_.ticket == ticket:
                return TradeOrder(**order_._asdict())
        return order

    async def get_orders(self, *, ticket: int = 0, symbol: str = '', group: str = '') -> tuple[TradeOrder, ...]:
        """Get the list of active pending orders for the current symbol.

        Keyword Args:
            ticket (int): Order ticket number
            symbol (str): Symbol name
            group (str): Group name
        Returns:
            tuple[TradeOrder]: A Tuple of active trade orders as TradeOrder objects
        """
        orders = await self.mt5.orders_get(symbol=symbol, ticket=ticket, group=group)
        if orders is not None:
            return tuple(TradeOrder(**order._asdict()) for order in orders)
        return tuple()

    @backoff_decorator
    async def check(self, **kwargs) -> OrderCheckResult:
        """Check funds sufficiency for performing a required trading operation and the possibility of executing it.

        Returns:
            OrderCheckResult: An OrderCheckResult object

        Raises:
            OrderError: If not successful
        """
        req = self.dict | kwargs
        res = await self.mt5.order_check(req)
        if res is None:
            raise OrderError(f'Order check failed for {self.symbol}')
        return res

    @backoff_decorator
    async def send(self) -> OrderSendResult:
        """Send a request to perform a trading operation from the terminal to the trade server.

        Returns:
             OrderSendResult: An OrderSendResult object

        Raises:
            OrderError: If not successful
        """
        res = await self.mt5.order_send(self.dict)
        if res is None:
            raise OrderError(f'Failed to send order {self.symbol}')
        return res

    async def calc_margin(self) -> float | None:
        """Return the required margin in the account currency to perform a specified trading operation.

        Returns:
            float: Returns float value if successful

        Raises:
            OrderError: If not successful
        """
        res = await self.mt5.order_calc_margin(self.type, self.symbol, self.volume, self.price)
        return res

    @error_handler(response=0)
    async def calc_profit(self) -> float:
        """Return profit in the account currency for a specified trading operation.

        Returns:
            float: Returns float value if successful
            None: If not successful
        """
        action, symbol, volume, price_open, price_close = self.type, self.symbol, self.volume, self.price, self.tp
        res = await self.mt5.order_calc_profit(action, symbol, volume, price_open, price_close)
        return res
