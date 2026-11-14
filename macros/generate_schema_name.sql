{#- Use the custom schema name as-is (raw, staging, intermediate, marts, snapshots) instead of
    dbt's default <target_schema>_<custom>, so the layers read like a warehouse. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
