import psutil
import dataclasses
import dotenv
import os
import discord
import asyncio
import signal
from discord.ext import tasks
from loguru import logger


def getenv(key: str) -> str:
    e = os.getenv(key)
    if e is None:
        raise Exception(f"{key} is not provided")
    return e


@dataclasses.dataclass
class MemoryMetrics:
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
        logger.info("Requested to start Palworld")
        if self._proc:
            logger.warning("Palworld is already running")
            return

        proc = await asyncio.create_subprocess_exec(
            self.palworld_bin, cwd=self.palworld_workdir
        )
        self._proc = proc
        logger.info("Palworld started")

    async def stop(self) -> None:
        logger.info("Requested to stop Palworld")
        if not self._proc:
            logger.warning("Palworld is not running")
            return

        # send SIGTERM to process
        self._proc.send_signal(signal.SIGTERM)
        logger.info("Sent SIGTERM to Palworld")

        # wait for process termination
        await self._proc.wait()
        self._proc = None
        logger.info("Palworld stopped")


class DiscordBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        dotenv.load_dotenv()
        self._discord_token = getenv("DISCORD_TOKEN")
        palworld_bin = getenv("PALWORLD_BIN")
        palworld_workdir = getenv("PALWORLD_WORKDIR")

        guild_id = int(getenv("TARGET_GUILD_ID"))
        self._target_guild_id = discord.Object(id=guild_id)

        self._pp = PalworldProcess(palworld_bin, palworld_workdir)

        self.tree = discord.app_commands.CommandTree(self)

    def run(self, *args, **kwargs) -> None:
        super().run(self._discord_token)

    async def setup_hook(self) -> None:
        logger.info("Waiting for Palworld to start...")
        await self._pp.start()
        logger.info("Palworld started")

        logger.info("Starting background metrics updater...")
        self.update_presence.start()
        logger.info("Started background metrics updater")

        logger.info("Registering commands...")
        self.tree.copy_global_to(guild=self._target_guild_id)
        await self.tree.sync(guild=self._target_guild_id)
        logger.info("Registered commands")

    async def restart_server(self):
        await self._pp.stop()
        await self._pp.start()

    async def stop_server(self):
        await self._pp.stop()

    async def start_server(self):
        await self._pp.start()

    @tasks.loop(seconds=60.0)
    async def update_presence(self) -> None:
        metrics = MemoryMetrics.fetch()

        memory_percent = metrics.used / metrics.total * 100
        swap_percent = metrics.swap_used / metrics.swap_total * 100

        text = f"Memory: {memory_percent:.1f}%; Swap: {swap_percent:.1f}%"
        logger.debug(text)

        # update presence
        await self.change_presence(
            status=discord.Status.online, activity=discord.CustomActivity(name=text)
        )
        logger.debug("Updated presence")

    @update_presence.before_loop
    async def before_update_presence(self) -> None:
        await self.wait_until_ready()

    async def on_ready(self) -> None:
        logger.info("Logged in as {0.user}".format(self))

    async def shutdown(self) -> None:
        logger.info("Shutting down...")
        await self._pp.stop()
        await self.close()
        logger.info("Shutdown completed")


client = DiscordBot()


@client.tree.command()
async def restart_server(interaction: discord.Interaction):
    logger.info("Received restart_server command")
    await interaction.response.defer(thinking=True)
    await client.restart_server()
    await interaction.followup.send("Restarted server")


@client.tree.command()
async def start_server(interaction: discord.Interaction):
    logger.info("Received start_server command")
    await interaction.response.defer(thinking=True)
    await client.start_server()
    await interaction.followup.send("Started server")


@client.tree.command()
async def stop_server(interaction: discord.Interaction):
    logger.info("Received stop_server command")
    await interaction.response.defer(thinking=True)
    await client.stop_server()
    await interaction.followup.send("Stopped server")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, k: asyncio.create_task(client.shutdown()))
    signal.signal(signal.SIGTERM, lambda s, k: asyncio.create_task(client.shutdown()))
    client.run()
