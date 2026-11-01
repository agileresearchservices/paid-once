"""What the show can run: the scenes and the numbers they use, the Nexus topology, and the ticket-ID convention.

Constants only (plus three small functions on ticket IDs). `scenes.py` plays the scenes; this says what they are.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from paidonce import config
from paidonce.lane2.contract import NEXUS_ENDPOINT, PaymentsService
from paidonce.lane2.payments_side import REFUND_START_TO_CLOSE, RefundWorkflow
from paidonce.lane2.support_side import SupportTicketWorkflow
from paidonce.models import RefundRequest, RefundResult

# A scene stays "running" after its script until every ticket has landed, so Run again never appears mid-flight.
SCENE_SETTLE_MAX_S = 45.0
SCENE_QUIET_S = 3.0

# How the show names each lane on screen; the code, ledger and ticket IDs keep lane1/lane2.
LANE_NAMES = {"lane1": "Queue + LangGraph", "lane2": "Temporal + Nexus"}

AGENT_WORKERS = ["lane1_worker", "support_worker"]

# The worker-crash scene (step 3): the first few approved refunds are in flight at payments when the workers die;
# the rest of the cohort is still waiting for a human.
WORKER_CRASH_COHORT = 6
WORKER_CRASH_IN_FLIGHT = 3

# Scored on their own and left out of the scoreboard totals: the walkthrough is a demonstration, and Nexus is its own step.
DEMO_SCENES = ("walkthrough", "nexus_kill")

# The Nexus gauntlet (step 7): four failures, each landing on refunds still in flight.
GAUNTLET_REFUNDS = 5  # refunds in the gauntlet, and how many payments stalls
GAUNTLET_STALL_S = REFUND_START_TO_CLOSE.total_seconds() + 1.0  # payments holds its reply past the activity's timeout
GAUNTLET_LATENCY_S = 2.0  # every payments call takes this long, so a kill lands mid-call
GAUNTLET_DOWN_S = {"support_worker": 5.0, "payments_worker": 6.0, "temporal": 5.0}

# The walkthrough (step 1): one ticket, with the refund slowed a little so it is visible in flight. Stays under Lane 1's
# 3 s payments client timeout, or its retry would book the refund twice on the happy path.
WALKTHROUGH_LATENCY_S = 2.5
# How long each walkthrough step stays on screen before the scene moves on, so a viewer can follow it unprompted. The
# "agent" step is also held until the agent has decided; this is its minimum.
WALKTHROUGH_END_HOLD_S = 2.5
WALKTHROUGH_DWELL_S = {"ticket": 3.5, "agent": 4.0, "waiting": 4.5, "approve": 4.0}
WALKTHROUGH_AMOUNT_CENTS = 4200
WALKTHROUGH_MESSAGE = "The mug arrived in pieces. Please refund me."

MESSAGES = [
    "The mug arrived in pieces. Please refund me.",
    "I was charged twice for the same order, please refund the duplicate.",
    "My package never arrived and tracking says delivered to the wrong city.",
    "The headphones are dead on arrival, I would like my money back.",
    "Wrong size shipped and the box was crushed. I want a refund.",
    "The blender leaks from the base and cracked on first use. Refund please.",
]


@dataclass
class SceneInfo:
    id: str
    title: str


SCENES = [
    SceneInfo("walkthrough", "Walkthrough: one ticket"),
    SceneInfo("intro", "Happy path"),
    SceneInfo("worker_crash", "The agent workers go down (crash or deploy)"),
    SceneInfo("double_delivery", "Double-delivered mail"),
    SceneInfo("payments_timeout", "Payments commits, then goes quiet"),
    SceneInfo("nexus_kill", "Nexus: four failures mid-refund"),
    SceneInfo("free_roam", "Free roam"),
]


# Who owns what across the Nexus boundary, from the same config and contract the workers use.
TOPOLOGY = {
    "support": {
        "namespace": config.SUPPORT_NAMESPACE,
        "task_queue": config.SUPPORT_TASK_QUEUE,
        "workflow": SupportTicketWorkflow.__name__,
    },
    "endpoint": NEXUS_ENDPOINT,
    "service": PaymentsService.__name__,
    "operation": "issue_refund",
    # The contract's two messages, field by field, read off the dataclasses so step 7 can't drift from the code.
    "sends": [f.name for f in fields(RefundRequest)],
    "returns": [f.name for f in fields(RefundResult)],
    "payments": {
        "namespace": config.PAYMENTS_NAMESPACE,
        "task_queue": config.PAYMENTS_TASK_QUEUE,
        "workflow": RefundWorkflow.__name__,
        "activity": "post_refund",
    },
}


def ticket_id(run_id: str, scene: str, run_no: int, i: int, lane: str) -> str:
    """`<reset id>-<scene>-r<run>-<index>-<lane>`: a re-run of a scene starts new workflows instead of colliding."""
    return f"{run_id}-{scene}-r{run_no}-{i:02d}-{lane}"


def ticket_index(tid: str) -> int:
    """The ticket's position in its cohort: ids end in `...-<index>-<lane>` (see ticket_id)."""
    return int(tid.rsplit("-", 2)[1])


def is_demo(tid: str) -> bool:
    """A walkthrough or Nexus-scene ticket, from any run: the scoreboard leaves them out (see DEMO_SCENES)."""
    return any(f"-{scene}-r" in tid for scene in DEMO_SCENES)
