import psutil
import dataclasses
import dotenv
import os
import discord
import asyncio
import signal


def getenv(key: str) -> str:
    e = os.getenv(key)
    if e is None:
        raise Exception(f"{key} is not provided")
    return e


class MemoryMetrics(dataclasses.dataclass):
    total: float
    used: float
    swap_total: float
    swap_used: float

    @classmethod
    def fetch(cls) -> "MemoryMetrics":
        mem = psutil.virtual_memory()
        swp = psutil.swap_memory()
        return MemoryMetrics(
            total=mem.total, used=mem.used, swap_total=swp.total, swap_used=swp.used
        )


class PalworldProcess:
    def __init__(self, palworld_bin: str, palworld_workdir: str) -> None:
        self.palworld_bin = palworld_bin
        self.palworld_workdir = palworld_workdir
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        if self._proc:
            return

        proc = await asyncio.create_subprocess_exec(
            self.palworld_bin, cwd=self.palworld_workdir
        )
        self._proc = proc

    async def stop(self) -> None:
        if not self._proc:
            return

        # send SIGTERM to process
        self._proc.send_signal(signal.SIGTERM)

        # wait for process termination
        await self._proc.wait()


class DiscordBot:
    def __init__(self):
        dotenv.load_dotenv()
        self._discord_token = getenv("DISCORD_TOKEN")
        palworld_bin = getenv("PALWORLD_BIN")
        palworld_workdir = getenv("PALWORLD_WORKDIR")

        self._pp = PalworldProcess(palworld_bin, palworld_workdir)
        self.client = discord.Client()

    async def start(self):
        await self.client.login(self._discord_token)

    async def periodic_update(self, period):
        while True:
            await self.update_presence()
            await asyncio.sleep(period)

    async def update_presence(self) -> None:
        metrics = MemoryMetrics.fetch()

        memory_percent = metrics.used / metrics.total * 100
        swap_percent = metrics.swap_used / metrics.swap_total * 100

        text = f"Memory {memory_percent:.1f}. Swap {swap_percent:.1f}"

        # update presence
        self.client.change_presence(
            status=discord.Status.online, activity=discord.CustomActivity(name=text)
        )
