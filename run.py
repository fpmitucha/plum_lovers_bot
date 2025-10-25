import os, sys, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from bot.main import main
asyncio.run(main())
