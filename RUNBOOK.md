# Runbook — first run

Two ways to get the pipeline running. **Option A (local)** is ready now and has
no AWS steps. **Option B (ECS schedule)** is the production path and needs a few
one-time AWS actions.

The two tables already exist in `social_golden_data` (created by hand). Apply
`sql/views.sql` after the first successful run.

---

## Option A — run locally tonight (ready now)

`.env` already points at the `postgres` role (write access to
`social_golden_data`).

```bash
uv sync
uv run main.py --dry-run          # sanity check, writes nothing
uv run main.py                    # first real run: opens a stint per track
```

To have it run unattended tonight, e.g. at 02:00:

```bash
echo "cd $(pwd) && $(command -v uv) run main.py >> run.log 2>&1" | at 02:00
# or add to crontab -e:
# 0 2 * * *  cd /Users/rosannadenigro/Desktop/PULSE/editorials_playlist && /opt/homebrew/bin/uv run main.py >> run.log 2>&1
```

Check afterwards:

```sql
select count(*), count(end_date) from social_golden_data.editorial_playlists_storico;  -- 2nd = 0 after a first run
select * from social_golden_data.editorial_playlists;                                   -- 15 rows
```

---

## Option B — ECS scheduled task

Config is prepared: the EventBridge schedule is `state = "ENABLED"`
(`terraform/editorials.tf`) and fires **daily at 00:00 UTC = 02:00 Europe/Rome**.
CI (`deploy-ecr.yml`) builds the image on push to `main` again.

Do these once, in order:

1. **Secrets Manager** — the secret that `secrets_manager_arn` points to must
   hold `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` with a role
   that can write to `social_golden_data` (the `postgres` creds in `.env`, or
   grant `metabase_user`: `INSERT, UPDATE` on both tables + `USAGE, SELECT` on
   `social_golden_data.editorial_playlists_storico_id_seq`).

2. **Image to ECR** — trigger the build:
   - GitHub → Actions → "Build and push image to ECR" → Run workflow, **or**
   - `AWS_PROFILE=... ./scripts/build_push_ecr.sh`

3. **Apply infra** (needs `terraform/terraform.tfvars` with `secrets_manager_arn`
   and `github_oidc_provider_arn`):
   ```bash
   cd terraform
   terraform init
   terraform apply
   ```

4. **Verify**:
   ```bash
   aws scheduler get-schedule --name daily-editorials-playlist-snapshot \
     --group-name "$(terraform -chdir=terraform output -raw schedule_group_name)" \
     --query 'State'                                          # -> "ENABLED"
   ```
   Optional smoke test now instead of waiting for 02:00:
   ```bash
   aws ecs run-task --cluster "$(terraform -chdir=terraform output -raw ecs_cluster_name)" \
     --task-definition "$(terraform -chdir=terraform output -raw ecs_task_definition_arn)" \
     --launch-type FARGATE \
     --network-configuration "awsvpcConfiguration={subnets=[<public-subnet-id>],securityGroups=[$(terraform -chdir=terraform output -raw ecs_security_group_id)],assignPublicIp=ENABLED}" \
     --overrides '{"containerOverrides":[{"name":"editorials-playlist-container","command":["uv","run","main.py"]}]}'
   ```
   Then watch `"$(terraform -chdir=terraform output -raw cloudwatch_log_group)"`.

> If you `terraform apply` **after** 00:00 UTC tonight, the first scheduled run
> is the following night — use the smoke test above to run it once immediately.

---

## After the first run

```bash
psql "$DATABASE_URL" -f sql/views.sql
```

Monitoring: the run prints `{"metric": "editorials_playlists_skipped", "value": N}`;
`terraform/alarms.tf` alarms on `> 0` (wire `alarm_sns_topic_arn` for a
notification).
