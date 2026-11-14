{#-
  Cross-database helpers. Models never call a dialect-specific function directly: they call these
  macros, and adapter.dispatch picks the implementation for the active adapter.
  duckdb__* is what dbt-duckdb runs; sqlite__* is used by the repo's SQLite test harness.
-#}

{% macro xdb_to_date(expr) %}{{ return(adapter.dispatch('xdb_to_date')(expr)) }}{% endmacro %}
{% macro default__xdb_to_date(expr) %}cast({{ expr }} as date){% endmacro %}
{% macro duckdb__xdb_to_date(expr) %}cast({{ expr }} as date){% endmacro %}
{% macro sqlite__xdb_to_date(expr) %}date({{ expr }}){% endmacro %}

{% macro xdb_to_timestamp(expr) %}{{ return(adapter.dispatch('xdb_to_timestamp')(expr)) }}{% endmacro %}
{% macro default__xdb_to_timestamp(expr) %}cast({{ expr }} as timestamp){% endmacro %}
{% macro duckdb__xdb_to_timestamp(expr) %}cast({{ expr }} as timestamp){% endmacro %}
{% macro sqlite__xdb_to_timestamp(expr) %}datetime({{ expr }}){% endmacro %}

{# first day of the month, as a date #}
{% macro xdb_month(expr) %}{{ return(adapter.dispatch('xdb_month')(expr)) }}{% endmacro %}
{% macro default__xdb_month(expr) %}cast(date_trunc('month', {{ expr }}) as date){% endmacro %}
{% macro duckdb__xdb_month(expr) %}cast(date_trunc('month', {{ expr }}) as date){% endmacro %}
{% macro sqlite__xdb_month(expr) %}date({{ expr }}, 'start of month'){% endmacro %}

{# whole days from start to end #}
{% macro xdb_days_between(start, end) %}{{ return(adapter.dispatch('xdb_days_between')(start, end)) }}{% endmacro %}
{% macro default__xdb_days_between(start, end) %}date_diff('day', cast({{ start }} as date), cast({{ end }} as date)){% endmacro %}
{% macro duckdb__xdb_days_between(start, end) %}date_diff('day', cast({{ start }} as date), cast({{ end }} as date)){% endmacro %}
{% macro sqlite__xdb_days_between(start, end) %}cast(julianday(date({{ end }})) - julianday(date({{ start }})) as integer){% endmacro %}

{# calendar months from start to end (month boundaries crossed) #}
{% macro xdb_months_between(start, end) %}{{ return(adapter.dispatch('xdb_months_between')(start, end)) }}{% endmacro %}
{% macro default__xdb_months_between(start, end) %}date_diff('month', cast({{ start }} as date), cast({{ end }} as date)){% endmacro %}
{% macro duckdb__xdb_months_between(start, end) %}date_diff('month', cast({{ start }} as date), cast({{ end }} as date)){% endmacro %}
{% macro sqlite__xdb_months_between(start, end) -%}
((cast(strftime('%Y', {{ end }}) as integer) - cast(strftime('%Y', {{ start }}) as integer)) * 12
 + cast(strftime('%m', {{ end }}) as integer) - cast(strftime('%m', {{ start }}) as integer))
{%- endmacro %}

{% macro xdb_add_days(expr, days) %}{{ return(adapter.dispatch('xdb_add_days')(expr, days)) }}{% endmacro %}
{% macro default__xdb_add_days(expr, days) %}({{ expr }} + ({{ days }}) * interval '1 day'){% endmacro %}
{% macro duckdb__xdb_add_days(expr, days) %}({{ expr }} + ({{ days }}) * interval '1 day'){% endmacro %}
{% macro sqlite__xdb_add_days(expr, days) %}datetime({{ expr }}, '{{ days }} days'){% endmacro %}

{# distinct values, sorted, comma-separated #}
{% macro xdb_listagg_distinct(expr) %}{{ return(adapter.dispatch('xdb_listagg_distinct')(expr)) }}{% endmacro %}
{% macro default__xdb_listagg_distinct(expr) %}string_agg(distinct {{ expr }}, ',' order by {{ expr }}){% endmacro %}
{% macro duckdb__xdb_listagg_distinct(expr) %}string_agg(distinct {{ expr }}, ',' order by {{ expr }}){% endmacro %}
{% macro sqlite__xdb_listagg_distinct(expr) %}group_concat(distinct {{ expr }} order by {{ expr }}){% endmacro %}
