from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION audit_event_append_only() RETURNS trigger AS $$
BEGIN
  -- Only allowed change: unlink a deleted user (actor_id -> NULL). Everything else is immutable.
  IF TG_OP = 'UPDATE' AND NEW.actor_id IS NULL
     AND (to_jsonb(NEW) - 'actor_id') = (to_jsonb(OLD) - 'actor_id') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'audit_auditevent is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_no_update_delete
BEFORE UPDATE OR DELETE ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION audit_event_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_event_no_update_delete ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_event_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
