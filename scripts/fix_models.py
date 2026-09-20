import re
from pathlib import Path

p = Path("apps/api/app/models.py")
text = p.read_text(encoding="utf-8")

# 1. fix literal backslash-n in imports
text = text.replace(
    "from datetime import datetime\\nfrom typing import Optional",
    "from datetime import datetime\nfrom typing import Optional",
)

# 2. fix doubled datetime annotations
text = re.sub(r"created_at: datetime: datetime", "created_at: datetime", text)
text = re.sub(r"updated_at: datetime: datetime", "updated_at: datetime", text)
text = re.sub(r"time: datetime: datetime", "time: datetime", text)

p.write_text(text, encoding="utf-8")
print("fixed")