"""Correlate bridge requests without retrying mutations."""
import asyncio
from uuid import uuid4


class RPC:
    def __init__(self, publish, base_topic, timeout=30):
        self.publish = publish
        self.base_topic = base_topic
        self.timeout = timeout
        self.pending = {}

    async def request(self, operation, payload):
        transaction = uuid4().hex
        key = (operation, transaction)
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            await self.publish(f'{self.base_topic}/bridge/request/{operation}',
                               {**payload, 'transaction': transaction})
            return await asyncio.wait_for(future, self.timeout)
        finally:
            self.pending.pop(key, None)
            if not future.done():
                future.cancel()

    def receive(self, operation, payload):
        future = self.pending.get((operation, payload.get('transaction')))
        if future is None or future.done():
            return
        if payload.get('status') == 'ok':
            future.set_result(payload.get('data', {}))
        else:
            future.set_exception(ValueError(str(payload.get('error', 'Bridge request failed'))))

    def close(self):
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError('Integration unloaded'))
