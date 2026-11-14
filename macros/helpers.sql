{# Portable helpers (plain ANSI SQL, no dispatch needed). #}

{% macro safe_divide(numerator, denominator) -%}
(cast({{ numerator }} as double) / nullif({{ denominator }}, 0))
{%- endmacro %}

{% macro revenue_status_list() -%}
({% for s in var('revenue_statuses') %}'{{ s }}'{% if not loop.last %}, {% endif %}{% endfor %})
{%- endmacro %}

{% macro clean_text(expr) -%}
nullif(lower(trim({{ expr }})), '')
{%- endmacro %}

{% macro as_of_date() -%}
{{ xdb_to_date("'" ~ var('as_of_date') ~ "'") }}
{%- endmacro %}
