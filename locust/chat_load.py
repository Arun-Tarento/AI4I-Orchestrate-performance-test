"""
Load test for POST /api/v1/chat (non-streaming).

N users fire the same fixed "turn 20" chat payload, round-robin across 3 API keys.
No login: API keys are long-lived and sent directly as Bearer tokens.

Run (from this directory, with .env filled in):
    locust -f chat_load.py -u 20 -r 1 --headless --run-time 2m

    # Or with the Locust UI:
    locust -f chat_load.py
"""

import itertools
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from locust import HttpUser, events, task

from config import API_KEYS, HOST, SERVICE_ID

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    print(f"\n[TEST START] {_ist_now()}")


@events.test_stop.add_listener
def _on_test_stop(environment, **kwargs):
    print(f"[TEST STOP]  {_ist_now()}")


ENDPOINT = "/api/v1/chat"

# Heaviest ("turn 20") payload: full conversation history plus tool definitions.
_PAYLOAD_FILE = os.path.join(os.path.dirname(__file__), "payloads", "chat_turn20.json")
with open(_PAYLOAD_FILE, "r", encoding="utf-8") as _f:
    PAYLOAD = json.load(_f)
PAYLOAD["stream"] = False  # forced off: the response handling below expects a single
                           # non-streaming completion object, not an SSE event stream
PAYLOAD["model"] = SERVICE_ID  # the payload's own "model" is a model NAME;
                               # /api/v1/chat requires a service ID here and
                               # 404s with the name

# Each user that spawns picks the next (name, key) pair in round-robin order.
# With 20 users and 3 keys: users 1,4,7,...  -> Admin
#                           users 2,5,8,...  -> Tenant Admin 1
#                           users 3,6,9,...  -> Tenant Admin 2
_key_cycle = itertools.cycle(API_KEYS.items())
_key_lock = threading.Lock()


@events.init_command_line_parser.add_listener
def _add_args(parser, **kwargs):
    existing = {s for a in parser._actions for s in a.option_strings}
    if "--think-time" not in existing:
        parser.add_argument(
            "--think-time",
            type=float,
            default=0.0,
            help="Seconds to wait between requests per user (default: 0, fire immediately)",
        )


class ChatUser(HttpUser):
    host = HOST

    def wait_time(self):
        return getattr(self.environment.parsed_options, "think_time", 0.0)

    def on_start(self) -> None:
        with _key_lock:
            self._key_name, self._api_key = next(_key_cycle)

    @task
    def chat(self) -> None:
        with self.client.post(
            ENDPOINT,
            json=PAYLOAD,
            headers={"Authorization": f"Bearer {self._api_key}"},
            catch_response=True,
            name=f"{ENDPOINT} [{self._key_name}]",
        ) as response:
            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                if choices and "message" in choices[0]:
                    response.success()
                else:
                    response.failure("200 but 'choices[0].message' missing in response")
            else:
                response.failure(f"{response.status_code}: {response.text[:200]}")
