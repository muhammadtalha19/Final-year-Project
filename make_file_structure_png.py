from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

out = Path("docs/diagrams/rendered_final/17_project_file_structure_tree.png")
out.parent.mkdir(parents=True, exist_ok=True)

W, H = 1450, 1150
img = Image.new("RGB", (W, H), "white")
draw = ImageDraw.Draw(img)

def font(size, bold=False):
    candidates = [
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/liberation/LiberationMono-Bold.ttf" if bold else "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

title_font = font(34, True)
text_font = font(24, False)
small_font = font(22, False)
caption_font = font(22, False)

x0, y0 = 70, 80

title = "Project File Structure — YAML-Based Multi-Cloud Deployment Orchestrator"
draw.text((x0, 30), title, font=title_font, fill="black")

lines = [
("📁 FYP/", ""),
("├── app.py", "Main Flask application and routes"),
("├── auth.py", "OAuth and login helpers"),
("├── config.py", "Application configuration"),
("├── config_schema.py", "YAML schema validation"),
("├── credential_vault.py", "Cloud credential encryption"),
("├── database.py", "Database initialization"),
("├── decision_engine.py", "Cloud provider selection logic"),
("├── diagnostics.py", "System diagnostics"),
("├── health_checks.py", "Endpoint health checking"),
("├── manage_db.py", "Database backup, upgrade and status"),
("├── manage_queue.py", "Redis/RQ queue status"),
("├── models.py", "User, CloudAccount, DeploymentRecord, AuditLog"),
("├── orchestrator.py", "Deployment orchestration workflow"),
("├── provider_readiness.py", "AWS/Azure/GCP readiness checks"),
("├── queue_utils.py", "Redis/RQ enqueue and queue availability"),
("├── tasks.py", "Background deployment job task"),
("├── worker.py", "RQ background worker process"),
("├── providers/", "Cloud provider adapter modules"),
("│   ├── base.py", "Common provider interface"),
("│   ├── aws_provider.py", "AWS EC2 deployment logic"),
("│   ├── azure_mock.py", "Azure Container Apps deployment logic"),
("│   └── gcp_mock.py", "GCP Cloud Run dry-run/readiness logic"),
("├── pricing/", "Pricing estimation modules"),
("├── templates/", "Jinja2 HTML frontend pages"),
("├── static/", "CSS, JavaScript and images"),
("├── migrations/", "Alembic database migration files"),
("├── tests/", "Automated pytest test suite"),
("├── docs/", "Report, diagrams and documentation"),
("├── examples/", "Sample YAML deployment files"),
("├── instance/", "Local SQLite database folder"),
("├── .env.example", "Environment variable template"),
("└── requirements.txt", "Python project dependencies"),
]

y = y0
line_h = 31
left_w = 610

# border
draw.rectangle((45, 20, W-45, H-70), outline=(180, 180, 180), width=2)

for left, right in lines:
    is_folder = left.strip().endswith("/")
    f = text_font if not is_folder else font(24, True)

    draw.text((x0, y), left, font=f, fill="black")

    if right:
        draw.text((x0 + left_w, y), "# " + right, font=small_font, fill=(40, 40, 40))

    y += line_h

caption = "Figure 2.12: Project File Structure"
bbox = draw.textbbox((0, 0), caption, font=caption_font)
draw.text(((W - (bbox[2]-bbox[0])) / 2, H-50), caption, font=caption_font, fill=(70, 70, 70))

img.save(out)
print(f"Created: {out}")
