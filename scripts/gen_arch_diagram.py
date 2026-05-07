"""Generate high-level enterprise architecture diagram for KubeRiva OMS."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(1, 1, figsize=(20, 14))
ax.set_xlim(0, 20)
ax.set_ylim(0, 14)
ax.axis("off")
fig.patch.set_facecolor("#0f1117")
ax.set_facecolor("#0f1117")

# ── Colour palette ──────────────────────────────────────────────────────────
C_CHANNEL   = "#1e3a5f"
C_API       = "#1a3a2a"
C_CORE      = "#2a1a3a"
C_WORKER    = "#3a2a0a"
C_DATA      = "#1a2a3a"
C_AI        = "#3a1a1a"
C_OUTBOUND  = "#1a3a3a"
C_BORDER    = "#2a2a3a"
C_TEXT      = "#e8e8f0"
C_LABEL     = "#a0a8c0"
C_ARROW     = "#4a5a7a"
C_HEAD      = "#6a8aaa"

def box(x, y, w, h, color, label=None, fontsize=9, border="#3a4a6a", radius=0.15):
    rect = FancyBboxPatch((x, y), w, h,
                          boxstyle=f"round,pad=0.0,rounding_size={radius}",
                          linewidth=1.2, edgecolor=border,
                          facecolor=color, zorder=2)
    ax.add_patch(rect)
    if label:
        ax.text(x + w/2, y + h/2, label, ha="center", va="center",
                fontsize=fontsize, color=C_TEXT, fontweight="bold",
                wrap=True, zorder=3,
                multialignment="center")

def section_label(x, y, text, color=C_LABEL):
    ax.text(x, y, text, ha="left", va="center",
            fontsize=7.5, color=color, fontstyle="italic", zorder=3)

def arrow(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=C_HEAD,
                                lw=1.2, mutation_scale=12),
                zorder=1)

def dbl_arrow(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="<|-|>", color=C_HEAD,
                                lw=1.2, mutation_scale=12),
                zorder=1)

# ── Title ────────────────────────────────────────────────────────────────────
ax.text(10, 13.5, "KubeRiva OMS — Enterprise Architecture",
        ha="center", va="center", fontsize=16, color=C_TEXT,
        fontweight="bold", zorder=3)

# ══════════════════════════════════════════════════════════════════════════════
# ROW 1 — Inbound Channels  (y=11.8 .. 12.8)
# ══════════════════════════════════════════════════════════════════════════════
section_label(0.3, 12.65, "INBOUND CHANNELS")
channels = ["Shopify", "Amazon SP", "WooCommerce", "BigCommerce", "Web / Direct API"]
cw = 3.2
gap = 0.3
start_x = (20 - len(channels)*cw - (len(channels)-1)*gap) / 2
for i, ch in enumerate(channels):
    bx = start_x + i*(cw+gap)
    box(bx, 11.8, cw, 0.85, C_CHANNEL, ch, fontsize=9, border="#2a5a9f")

# ══════════════════════════════════════════════════════════════════════════════
# ROW 2 — API Gateway  (y=10.4 .. 11.4)
# ══════════════════════════════════════════════════════════════════════════════
arrow(10, 11.8, 10, 11.4)
section_label(0.3, 11.28, "API GATEWAY")
box(1.5, 10.4, 17, 0.85, C_API, border="#2a6a4a")
ax.text(6.0, 10.825, "FastAPI  ·  JWT Auth  ·  Rate Limiting  ·  CORS", ha="center", va="center",
        fontsize=9.5, color=C_TEXT, fontweight="bold", zorder=3)
ax.text(13.5, 10.825, "REST + WebSocket  ·  OpenAPI / Swagger  ·  Multi-Tenant Router",
        ha="center", va="center", fontsize=9, color=C_LABEL, zorder=3)

# ══════════════════════════════════════════════════════════════════════════════
# ROW 3 — Core Services  (y=8.9 .. 10.0)
# ══════════════════════════════════════════════════════════════════════════════
arrow(10, 10.4, 10, 10.0)
section_label(0.3, 9.88, "CORE SERVICES")
services = [
    "Order\nManagement",
    "Sourcing\nEngine",
    "Inventory\nManagement",
    "Fulfillment\nPipeline",
    "Connector\nHub",
]
sw = 3.3
sgap = 0.275
sx0 = (20 - len(services)*sw - (len(services)-1)*sgap) / 2
for i, svc in enumerate(services):
    bx = sx0 + i*(sw+sgap)
    box(bx, 8.9, sw, 1.0, C_CORE, svc, fontsize=8.5, border="#6a3a9f")

# ══════════════════════════════════════════════════════════════════════════════
# ROW 4 — Async Workers  (y=7.35 .. 8.5)
# ══════════════════════════════════════════════════════════════════════════════
arrow(10, 8.9, 10, 8.5)
section_label(0.3, 8.38, "ASYNC WORKERS  (Celery)")
queues = ["Sourcing\nQueue", "Fulfillment\nQueue", "Carrier\nQueue",
          "Webhooks\nQueue", "Connectors\nQueue", "Notifications\nQueue"]
qw = 2.9
qgap = 0.22
qx0 = (20 - len(queues)*qw - (len(queues)-1)*qgap) / 2
for i, q in enumerate(queues):
    bx = qx0 + i*(qw+qgap)
    box(bx, 7.35, qw, 0.95, C_WORKER, q, fontsize=8, border="#9a6a1a")

# ══════════════════════════════════════════════════════════════════════════════
# ROW 5a — Data Stores  (y=5.8 .. 7.0)   LEFT side
# ══════════════════════════════════════════════════════════════════════════════
dbl_arrow(10, 7.35, 10, 7.0)
section_label(0.3, 6.88, "DATA LAYER")
datastores = [
    ("PostgreSQL", "Orders · Inventory\nRules · Users · Orgs"),
    ("MongoDB", "Audit Events\nAI Learning Outcomes"),
    ("Redis", "Cache · Session\nCelery Broker"),
    ("Elasticsearch", "Full-text Search\nOrder Lookup"),
]
dw = 4.4
dgap = 0.27
dx0 = (20 - len(datastores)*dw - (len(datastores)-1)*dgap) / 2
for i, (title, sub) in enumerate(datastores):
    bx = dx0 + i*(dw+dgap)
    box(bx, 5.8, dw, 1.05, C_DATA, border="#1a5a8a")
    ax.text(bx + dw/2, 5.8 + 0.72, title, ha="center", va="center",
            fontsize=9, color=C_TEXT, fontweight="bold", zorder=3)
    ax.text(bx + dw/2, 5.8 + 0.3, sub, ha="center", va="center",
            fontsize=7.5, color=C_LABEL, zorder=3)

# ══════════════════════════════════════════════════════════════════════════════
# ROW 6 — AI Layer  (y=4.2 .. 5.45)
# ══════════════════════════════════════════════════════════════════════════════
arrow(10, 5.8, 10, 5.45)
section_label(0.3, 5.33, "AI / ML LAYER")
ai_blocks = [
    ("BYO LLM\nIntegration", "Claude · GPT · Gemini\nOllama / LiteLLM"),
    ("AI-Adaptive\nSourcing", "Node scoring · Fallback\nto Distance-Optimal"),
    ("Pattern\nDiscovery", "Cluster analysis\nMin 50 samples"),
    ("A/B Experiment\nEngine", "Traffic splitting\nOutcome evaluation"),
]
aw = 4.4
agap = 0.27
ax0_ = (20 - len(ai_blocks)*aw - (len(ai_blocks)-1)*agap) / 2
for i, (title, sub) in enumerate(ai_blocks):
    bx = ax0_ + i*(aw+agap)
    box(bx, 4.2, aw, 1.1, C_AI, border="#9a2a2a")
    ax.text(bx + aw/2, 4.2 + 0.75, title, ha="center", va="center",
            fontsize=9, color=C_TEXT, fontweight="bold", zorder=3)
    ax.text(bx + aw/2, 4.2 + 0.3, sub, ha="center", va="center",
            fontsize=7.5, color=C_LABEL, zorder=3)

# ══════════════════════════════════════════════════════════════════════════════
# ROW 7 — Outbound  (y=2.65 .. 3.85)
# ══════════════════════════════════════════════════════════════════════════════
arrow(10, 4.2, 10, 3.85)
section_label(0.3, 3.73, "OUTBOUND INTEGRATIONS")
out_blocks = [
    ("Carrier APIs", "FedEx · UPS · DHL\nTracking updates"),
    ("Webhook\nDelivery", "HMAC-signed\n5-retry backoff"),
    ("Shopify / Amazon\nFulfillment Push", "Real-time sync\nback to channel"),
    ("Notifications", "Email · SMS\nSlack alerts"),
]
ow = 4.4
ogap = 0.27
ox0 = (20 - len(out_blocks)*ow - (len(out_blocks)-1)*ogap) / 2
for i, (title, sub) in enumerate(out_blocks):
    bx = ox0 + i*(ow+ogap)
    box(bx, 2.65, ow, 1.05, C_OUTBOUND, border="#1a7a7a")
    ax.text(bx + ow/2, 2.65 + 0.72, title, ha="center", va="center",
            fontsize=9, color=C_TEXT, fontweight="bold", zorder=3)
    ax.text(bx + ow/2, 2.65 + 0.3, sub, ha="center", va="center",
            fontsize=7.5, color=C_LABEL, zorder=3)

# ══════════════════════════════════════════════════════════════════════════════
# Footer legend
# ══════════════════════════════════════════════════════════════════════════════
legend_items = [
    (C_CHANNEL, "Inbound Channels"),
    (C_API,     "API Gateway"),
    (C_CORE,    "Core Services"),
    (C_WORKER,  "Async Workers"),
    (C_DATA,    "Data Layer"),
    (C_AI,      "AI / ML Layer"),
    (C_OUTBOUND,"Outbound"),
]
lx = 1.0
for color, label in legend_items:
    patch = mpatches.Patch(facecolor=color, edgecolor="#4a5a7a", linewidth=0.8)
    ax.text(lx + 0.35, 1.8, label, va="center", fontsize=7.5, color=C_LABEL, zorder=3)
    rect = FancyBboxPatch((lx, 1.67), 0.28, 0.28,
                          boxstyle="round,pad=0.0,rounding_size=0.05",
                          linewidth=0.8, edgecolor="#4a5a7a", facecolor=color, zorder=3)
    ax.add_patch(rect)
    lx += 2.55

ax.text(10, 1.1, "github.com/KubeRiva/OMS  ·  Apache 2.0  ·  kuberiva-oms on PyPI",
        ha="center", va="center", fontsize=8, color="#5a6a8a", zorder=3)

plt.tight_layout(pad=0)
out = "D:/KubeRiva/OMS/docs/architecture.png"
plt.savefig(out, dpi=180, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close()
print(f"Saved: {out}")
