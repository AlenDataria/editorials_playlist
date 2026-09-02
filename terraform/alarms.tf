# Turn the per-run "editorials_playlists_skipped" JSON line (printed on stdout by
# src/processor.py) into a CloudWatch metric, and alarm when it is > 0.
#
# The app emits one line per run like:  {"metric": "editorials_playlists_skipped", "value": 2}

resource "aws_cloudwatch_log_metric_filter" "playlists_skipped" {
  name           = "${var.project_name}-playlists-skipped"
  log_group_name = aws_cloudwatch_log_group.ecs_tasks.name
  pattern        = "{ $.metric = \"editorials_playlists_skipped\" }"

  metric_transformation {
    name          = "editorials_playlists_skipped"
    namespace     = "EditorialsPlaylist"
    value         = "$.value"
    default_value = "0"
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "playlists_skipped" {
  alarm_name          = "${var.project_name}-playlists-skipped"
  alarm_description   = "A daily editorials run skipped one or more playlists (fetch failure or partial response). Check the CloudWatch logs and reconcile the affected playlists by hand."
  namespace           = "EditorialsPlaylist"
  metric_name         = "editorials_playlists_skipped"
  statistic           = "Maximum"
  period              = 86400 # one daily run
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []

  tags = {
    Name      = "${var.project_name}-playlists-skipped"
    Project   = var.project_name
    ManagedBy = "Terraform"
  }
}
