"""One-shot conversion: introspect-CSV → schema.sql.

Usage:
    python schema/_csv_to_schema.py < introspect_output.csv > schema/schema.sql

Or with the CSV embedded (as it currently is below).

Why this exists: schema/introspect.sql failed on the Supabase SQL editor
with a parser quirk around literal DDL strings. The workaround is to
dump column metadata as DATA via a plain SELECT, then format the DDL on
the client side — this script does the formatting.

Once you have DATABASE_URL set, you can retire this script and use
schema_dump.py directly. Until then, this is the reliable path.
"""
import csv
import sys
from collections import OrderedDict


def build_schema(csv_text: str) -> str:
    rows_by_table = OrderedDict()
    reader = csv.DictReader(csv_text.splitlines())
    for row in reader:
        rows_by_table.setdefault(row["table_name"], []).append(row)

    out = []
    out.append("-- schema.sql")
    out.append("-- Live snapshot of the Supabase public schema, captured 2026-05-11.")
    out.append("-- Generated via schema/_csv_to_schema.py from the metadata-dump CSV.")
    out.append("-- See schema/README.md for the regen workflow.")
    out.append("--")
    out.append("-- Tables + columns only. Constraints (PK / FK / UNIQUE) and indexes")
    out.append("-- still need to be captured separately - run schema/introspect.sql")
    out.append("-- Queries 2 and 3 in the Supabase SQL editor and paste the results")
    out.append("-- at the bottom of this file under their respective section headers.")
    out.append("")
    out.append('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    out.append("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    out.append("")

    for table_name, rows in sorted(rows_by_table.items()):
        rows.sort(key=lambda r: int(r["ordinal"]))
        out.append("-- " + ("-" * 70))
        out.append(f"-- Table: {table_name}")
        out.append("-- " + ("-" * 70))
        out.append(f"CREATE TABLE IF NOT EXISTS public.{table_name} (")
        col_lines = []
        for r in rows:
            col = r["column_name"]
            dtype = r["data_type"]
            default = r["column_default"] if r["column_default"] != "null" else None
            not_null = r["not_null"] == "true"

            # nextval() defaults → use SERIAL family so a fresh DB
            # auto-creates the sequence. Original sequence names are lost,
            # but Postgres will name them <table>_<col>_seq which matches.
            if default and "nextval(" in default:
                if dtype == "bigint":
                    dtype = "BIGSERIAL"
                    default = None
                    not_null = False  # SERIAL implies NOT NULL
                elif dtype == "integer":
                    dtype = "SERIAL"
                    default = None
                    not_null = False
                elif dtype == "smallint":
                    dtype = "SMALLSERIAL"
                    default = None
                    not_null = False

            # Normalize type names for readability
            dtype = dtype.replace("timestamp with time zone", "TIMESTAMPTZ")
            dtype = dtype.replace("character varying", "VARCHAR")

            parts = [f"  {col} {dtype}"]
            if default:
                parts.append(f"DEFAULT {default}")
            if not_null:
                parts.append("NOT NULL")
            col_lines.append(" ".join(parts))

        out.append(",\n".join(col_lines))
        out.append(");")
        out.append("")

    # Placeholder sections for the constraint + index follow-up dumps.
    # Run the two queries in schema/README.md or schema/introspect.sql
    # (Queries 2 and 3) and paste the result rows BELOW the matching
    # header. Keeping these placeholders here means schema.sql is
    # self-documenting — the next dev can see what's expected.
    sep = "-- " + ("-" * 70)
    out.append(sep)
    out.append("-- CONSTRAINTS")
    out.append("-- (paste Query 2 results below - see schema/README.md)")
    out.append(sep)
    out.append("")
    out.append(sep)
    out.append("-- INDEXES")
    out.append("-- (paste Query 3 results below - see schema/README.md)")
    out.append(sep)
    out.append("")

    return "\n".join(out)


# Embedded CSV — replace with stdin read if you re-run this script
# after a future schema introspection dump. For now the 2026-05-11
# snapshot is inlined so the script is self-contained.
EMBEDDED_CSV = r"""table_name,column_name,data_type,not_null,column_default,ordinal
audit_log,id,uuid,true,gen_random_uuid(),1
audit_log,actor_email,text,true,null,2
audit_log,actor_id,text,false,null,3
audit_log,action,text,true,null,4
audit_log,entity_type,text,false,null,5
audit_log,entity_id,text,false,null,6
audit_log,before,jsonb,false,null,7
audit_log,after,jsonb,false,null,8
audit_log,metadata,jsonb,false,null,9
audit_log,ip_address,inet,false,null,10
audit_log,user_agent,text,false,null,11
audit_log,created_at,timestamp with time zone,false,now(),12
confirmed_purchases,id,bigint,true,nextval('confirmed_purchases_id_seq'::regclass),1
confirmed_purchases,purchase_id,text,true,null,2
confirmed_purchases,company,text,true,null,3
confirmed_purchases,ticker,text,false,''::text,4
confirmed_purchases,btc_amount,numeric,false,0,5
confirmed_purchases,usd_amount,numeric,false,0,6
confirmed_purchases,price_per_btc,numeric,false,0,7
confirmed_purchases,filing_date,text,true,null,8
confirmed_purchases,filing_url,text,false,''::text,9
confirmed_purchases,was_predicted,boolean,false,false,10
confirmed_purchases,prediction_id,text,false,null,11
confirmed_purchases,prediction_lead_time_hours,numeric,false,null,12
confirmed_purchases,confirmed_at,timestamp with time zone,false,now(),13
confirmed_purchases,source,text,false,''::text,14
confirmed_sales,sale_id,text,true,null,1
confirmed_sales,company,text,true,null,2
confirmed_sales,ticker,text,false,null,3
confirmed_sales,btc_amount,numeric,true,null,4
confirmed_sales,usd_amount,numeric,false,0,5
confirmed_sales,price_per_btc,numeric,false,0,6
confirmed_sales,filing_date,date,false,null,7
confirmed_sales,filing_url,text,false,null,8
confirmed_sales,source,text,false,null,9
confirmed_sales,created_at,timestamp with time zone,false,now(),10
data_freshness,id,bigint,true,nextval('data_freshness_id_seq'::regclass),1
data_freshness,snapshot_time,timestamp with time zone,true,null,2
data_freshness,overall_health,text,false,'unknown'::text,3
data_freshness,live_count,integer,false,0,4
data_freshness,stale_count,integer,false,0,5
data_freshness,unavailable_count,integer,false,0,6
data_freshness,sources_json,jsonb,false,'[]'::jsonb,7
data_freshness,provenance_json,jsonb,false,'{}'::jsonb,8
edgar_companies,id,bigint,true,nextval('edgar_companies_id_seq'::regclass),1
edgar_companies,cik,text,true,null,2
edgar_companies,company,text,true,null,3
edgar_companies,ticker,text,true,null,4
edgar_companies,priority,text,false,'medium'::text,5
edgar_companies,is_active,boolean,false,true,6
edgar_companies,created_at,timestamp with time zone,false,now(),7
edgar_filings,id,integer,true,nextval('edgar_filings_id_seq'::regclass),1
edgar_filings,accession_number,character varying(50),true,null,2
edgar_filings,company_name,character varying(200),false,null,3
edgar_filings,ticker_cik,character varying(50),false,null,4
edgar_filings,filing_date,date,false,null,5
edgar_filings,form_type,character varying(20),false,null,6
edgar_filings,event_type,character varying(20),false,null,7
edgar_filings,btc_amount,numeric,false,0,8
edgar_filings,usd_amount,numeric,false,0,9
edgar_filings,filing_url,character varying(500),false,null,10
edgar_filings,processed_at,timestamp with time zone,false,now(),11
edgar_filings,source,text,false,null,12
leaderboard_snapshots,id,bigint,true,nextval('leaderboard_snapshots_id_seq'::regclass),1
leaderboard_snapshots,snapshot_date,text,true,null,2
leaderboard_snapshots,btc_price,numeric,false,0,3
leaderboard_snapshots,total_btc,bigint,false,0,4
leaderboard_snapshots,total_value_b,numeric,false,0,5
leaderboard_snapshots,companies_json,text,false,'[]'::text,6
leaderboard_snapshots,created_at,timestamp with time zone,false,now(),7
leaderboard_snapshots,entity_count,integer,false,0,8
learned_weights,id,bigint,true,nextval('learned_weights_id_seq'::regclass),1
learned_weights,weight_key,text,true,null,2
learned_weights,category,text,true,null,3
learned_weights,original_weight,numeric,false,0,4
learned_weights,learned_adjustment,numeric,false,0,5
learned_weights,effective_weight,numeric,false,0,6
learned_weights,success_count,integer,false,0,7
learned_weights,failure_count,integer,false,0,8
learned_weights,success_rate,numeric,false,0,9
learned_weights,last_updated,timestamp with time zone,false,now(),10
narratives,id,bigint,true,nextval('narratives_id_seq'::regclass),1
narratives,narrative_type,text,true,null,2
narratives,narrative_date,text,true,null,3
narratives,content,text,false,''::text,4
narratives,generated_at,timestamp with time zone,false,now(),5
new_entrants,id,bigint,true,nextval('new_entrants_id_seq'::regclass),1
new_entrants,ticker,text,true,null,2
new_entrants,company,text,false,null,3
new_entrants,btc_holdings,integer,false,0,4
new_entrants,first_seen,date,true,CURRENT_DATE,5
new_entrants,notified,boolean,false,false,6
notable_statements,id,bigint,true,nextval('notable_statements_id_seq'::regclass),1
notable_statements,statement_id,text,true,null,2
notable_statements,person,text,true,null,3
notable_statements,title,text,false,''::text,4
notable_statements,date,text,false,''::text,5
notable_statements,statement,text,false,''::text,6
notable_statements,impact,text,false,''::text,7
notable_statements,category,text,false,''::text,8
notable_statements,source_url,text,false,''::text,9
notable_statements,auto_detected,boolean,false,false,10
notable_statements,created_at,timestamp with time zone,false,now(),11
pending_purchases,id,bigint,true,nextval('pending_purchases_id_seq'::regclass),1
pending_purchases,pending_id,text,true,null,2
pending_purchases,company,text,true,null,3
pending_purchases,ticker,text,true,null,4
pending_purchases,btc_amount,numeric,false,0,5
pending_purchases,usd_amount,numeric,false,0,6
pending_purchases,price_per_btc,numeric,false,0,7
pending_purchases,detected_date,text,true,null,8
pending_purchases,source,text,true,null,9
pending_purchases,source_rank,integer,false,4,10
pending_purchases,notes,text,false,''::text,11
pending_purchases,status,text,false,'pending'::text,12
pending_purchases,confirmed_at,timestamp with time zone,false,null,13
pending_purchases,confirmed_by,text,false,null,14
pending_purchases,created_at,timestamp with time zone,false,now(),15
pending_purchases,is_new_entrant,boolean,false,false,16
pending_purchases,transaction_type,text,false,'purchase'::text,17
predictions,id,bigint,true,nextval('predictions_id_seq'::regclass),1
predictions,prediction_id,text,true,null,2
predictions,company,text,true,null,3
predictions,ticker,text,false,''::text,4
predictions,signal_type,text,true,null,5
predictions,signal_score,integer,false,0,6
predictions,signal_details,text,false,''::text,7
predictions,predicted_at,timestamp with time zone,false,now(),8
predictions,was_correct,boolean,false,null,9
predictions,matched_purchase_id,text,false,null,10
predictions,notes,text,false,''::text,11
price_predictions,id,bigint,true,nextval('price_predictions_id_seq'::regclass),1
price_predictions,prediction_date,text,true,null,2
price_predictions,insights_json,text,false,'{}'::text,3
price_predictions,headline,text,false,''::text,4
price_predictions,generated_at,timestamp with time zone,false,now(),5
regulatory_items,id,bigint,true,nextval('regulatory_items_id_seq'::regclass),1
regulatory_items,item_id,text,true,null,2
regulatory_items,title,text,true,null,3
regulatory_items,category,text,false,''::text,4
regulatory_items,type,text,false,''::text,5
regulatory_items,status,text,false,''::text,6
regulatory_items,status_color,text,false,'yellow'::text,7
regulatory_items,date_updated,text,false,''::text,8
regulatory_items,summary,text,false,''::text,9
regulatory_items,impact,text,false,''::text,10
regulatory_items,btc_impact,text,false,''::text,11
regulatory_items,country,text,false,''::text,12
regulatory_items,source_url,text,false,''::text,13
regulatory_items,auto_detected,boolean,false,false,14
regulatory_items,created_at,timestamp with time zone,false,now(),15
subscribers,id,bigint,true,nextval('subscribers_id_seq'::regclass),1
subscribers,subscriber_id,text,true,null,2
subscribers,name,text,true,null,3
subscribers,email,text,true,null,4
subscribers,role,text,false,''::text,5
subscribers,company_name,text,true,null,6
subscribers,ticker,text,false,''::text,7
subscribers,sector,text,false,''::text,8
subscribers,country,text,false,''::text,9
subscribers,btc_holdings,numeric,false,0,10
subscribers,avg_purchase_price,numeric,false,0,11
subscribers,total_invested_usd,numeric,false,0,12
subscribers,plan,text,false,'pro'::text,13
subscribers,is_active,boolean,false,true,14
subscribers,alert_frequency,text,false,'instant'::text,15
subscribers,email_briefing,boolean,false,true,16
subscribers,telegram_chat_id,text,false,''::text,17
subscribers,watchlist_json,jsonb,false,'[]'::jsonb,18
subscribers,created_at,timestamp with time zone,false,now(),19
subscribers,last_active,timestamp with time zone,false,now(),20
subscribers,password_hash,text,false,''::text,21
subscribers,stripe_customer_id,text,false,''::text,22
subscribers,stripe_subscription_id,text,false,''::text,23
subscribers,pending_plan,text,false,''::text,24
subscribers,api_key,text,false,''::text,25
subscribers,shares_outstanding,bigint,false,0,26
subscribers,api_key_hash,text,false,null,27
subscribers,api_key_last4,text,false,null,28
subscribers,api_key_created_at,timestamp with time zone,false,null,29
subscribers,api_key_revoked_at,timestamp with time zone,false,null,30
subscribers,user_type,character varying(20),false,'entity'::character varying,31
subscribers,entity_category,character varying(30),false,''::character varying,32
subscribers,entity_id,character varying(50),false,''::character varying,33
subscribers,team_id,uuid,false,null,34
subscribers,team_role,text,false,null,35
subscribers,trial_started_at,timestamp with time zone,false,null,36
subscribers,trial_emails_sent_json,jsonb,true,'[]'::jsonb,37
team_invites,id,uuid,true,gen_random_uuid(),1
team_invites,team_id,uuid,true,null,2
team_invites,email,text,true,null,3
team_invites,token,text,true,null,4
team_invites,invited_by,text,true,null,5
team_invites,status,text,true,'pending'::text,6
team_invites,expires_at,timestamp with time zone,true,null,7
team_invites,accepted_at,timestamp with time zone,false,null,8
team_invites,created_at,timestamp with time zone,false,now(),9
teams,id,uuid,true,gen_random_uuid(),1
teams,name,text,true,null,2
teams,owner_id,text,true,null,3
teams,plan,text,true,'team'::text,4
teams,seat_limit,integer,false,null,5
teams,stripe_customer_id,text,false,null,6
teams,stripe_subscription_id,text,false,null,7
teams,created_at,timestamp with time zone,false,now(),8
teams,updated_at,timestamp with time zone,false,now(),9
teams,watchlist_json,jsonb,true,'[]'::jsonb,10
teams,slack_webhook_url,text,false,null,11
treasury_companies,id,bigint,true,nextval('treasury_companies_id_seq'::regclass),1
treasury_companies,ticker,text,true,null,2
treasury_companies,company,text,true,null,3
treasury_companies,btc_holdings,integer,false,0,4
treasury_companies,avg_purchase_price,numeric,false,0,5
treasury_companies,total_cost_usd,numeric,false,0,6
treasury_companies,country,text,false,''::text,7
treasury_companies,sector,text,false,''::text,8
treasury_companies,is_government,boolean,false,false,9
treasury_companies,data_source,text,false,'seed'::text,10
treasury_companies,last_updated,timestamp with time zone,false,now(),11
treasury_companies,entity_type,text,false,'public_company'::text,12
treasury_companies,shares_outstanding,bigint,false,0,13
treasury_companies,source_updated_at,timestamp with time zone,false,null,14
treasury_companies,last_seen_in_source,timestamp with time zone,false,null,15
treasury_history,id,bigint,true,nextval('treasury_history_id_seq'::regclass),1
treasury_history,ticker,text,true,null,2
treasury_history,company,text,false,null,3
treasury_history,btc_holdings,integer,false,0,4
treasury_history,snapshot_date,date,true,CURRENT_DATE,5
tweets,id,bigint,true,nextval('tweets_id_seq'::regclass),1
tweets,tweet_id,text,true,null,2
tweets,author_username,text,true,null,3
tweets,company,text,false,''::text,4
tweets,tweet_text,text,true,null,5
tweets,tweet_url,text,false,''::text,6
tweets,created_at,text,true,null,7
tweets,like_count,integer,false,0,8
tweets,retweet_count,integer,false,0,9
tweets,view_count,integer,false,0,10
tweets,is_reply,boolean,false,false,11
tweets,is_signal,boolean,false,false,12
tweets,confidence_score,integer,false,0,13
tweets,processed,boolean,false,false,14
tweets,inserted_at,timestamp with time zone,false,now(),15
user_saved_views,id,uuid,true,gen_random_uuid(),1
user_saved_views,user_id,text,true,null,2
user_saved_views,team_id,text,false,null,3
user_saved_views,page,text,true,null,4
user_saved_views,name,text,true,null,5
user_saved_views,filters,jsonb,true,'{}'::jsonb,6
user_saved_views,created_at,timestamp with time zone,false,now(),7
user_saved_views,updated_at,timestamp with time zone,false,now(),8
verification_codes,id,bigint,true,nextval('verification_codes_id_seq'::regclass),1
verification_codes,email,text,true,null,2
verification_codes,code,text,true,null,3
verification_codes,created_at,timestamp with time zone,false,now(),4
verification_codes,expires_at,timestamp with time zone,false,(now() + '00:10:00'::interval),5
verification_codes,used,boolean,false,false,6
whale_transactions,id,integer,true,nextval('whale_transactions_id_seq'::regclass),1
whale_transactions,tx_hash,character varying(100),true,null,2
whale_transactions,btc_amount,numeric,false,0,3
whale_transactions,entity_name,character varying(200),false,null,4
whale_transactions,direction,character varying(200),false,null,5
whale_transactions,detected_at,timestamp with time zone,false,now(),6
"""


def _force_utf8_stdout():
    """On Windows, sys.stdout uses cp1252 by default when piped — that
    breaks any non-ASCII output (em-dashes, box-drawing chars). Force
    UTF-8 reconfiguration so `python _csv_to_schema.py > schema.sql`
    produces a UTF-8 file regardless of shell encoding."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # py3.7+
    except Exception:
        pass


if __name__ == "__main__":
    _force_utf8_stdout()
    # If stdin has data, prefer it; otherwise use the embedded snapshot.
    if not sys.stdin.isatty():
        csv_text = sys.stdin.read()
        if not csv_text.strip():
            csv_text = EMBEDDED_CSV
    else:
        csv_text = EMBEDDED_CSV
    sys.stdout.write(build_schema(csv_text))
