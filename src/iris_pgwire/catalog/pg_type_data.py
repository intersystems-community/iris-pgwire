"""pg_type rows captured from a real PostgreSQL. Generated: do not edit by hand.

Source: PostgreSQL 16.15 (Debian 16.15-1.pgdg12+2) with pgvector 0.8.7, captured 2026-10-24 by scripts/capture_pg_type.py.
Regenerate with that script; tests/unit/test_pg_type_view.py pins the invariants.
The `vector` type and its array are renumbered to 16388 and 16389.
"""

# fmt: off
PG_TYPE_COLUMNS = ('oid', 'typname', 'typnamespace', 'typowner', 'typlen', 'typbyval', 'typtype', 'typcategory', 'typispreferred', 'typisdefined', 'typdelim', 'typrelid', 'typsubscript', 'typelem', 'typarray', 'typinput', 'typoutput', 'typreceive', 'typsend', 'typmodin', 'typmodout', 'typanalyze', 'typalign', 'typstorage', 'typnotnull', 'typbasetype', 'typtypmod', 'typndims', 'typcollation', 'typdefaultbin', 'typdefault', 'typacl')

PG_TYPE_ROWS = (
    (16, 'bool', 11, 10, 1, True, 'b', 'B', True, True, ',', 0, '-', 0, 1000, 'boolin', 'boolout', 'boolrecv', 'boolsend', '-', '-', '-', 'c', 'p', False, 0, -1, 0, 0, None, None, None),
    (17, 'bytea', 11, 10, -1, False, 'b', 'U', False, True, ',', 0, '-', 0, 1001, 'byteain', 'byteaout', 'bytearecv', 'byteasend', '-', '-', '-', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (18, 'char', 11, 10, 1, True, 'b', 'Z', False, True, ',', 0, '-', 0, 1002, 'charin', 'charout', 'charrecv', 'charsend', '-', '-', '-', 'c', 'p', False, 0, -1, 0, 0, None, None, None),
    (19, 'name', 11, 10, 64, False, 'b', 'S', False, True, ',', 0, 'raw_array_subscript_handler', 18, 1003, 'namein', 'nameout', 'namerecv', 'namesend', '-', '-', '-', 'c', 'p', False, 0, -1, 0, 950, None, None, None),
    (20, 'int8', 11, 10, 8, True, 'b', 'N', False, True, ',', 0, '-', 0, 1016, 'int8in', 'int8out', 'int8recv', 'int8send', '-', '-', '-', 'd', 'p', False, 0, -1, 0, 0, None, None, None),
    (21, 'int2', 11, 10, 2, True, 'b', 'N', False, True, ',', 0, '-', 0, 1005, 'int2in', 'int2out', 'int2recv', 'int2send', '-', '-', '-', 's', 'p', False, 0, -1, 0, 0, None, None, None),
    (23, 'int4', 11, 10, 4, True, 'b', 'N', False, True, ',', 0, '-', 0, 1007, 'int4in', 'int4out', 'int4recv', 'int4send', '-', '-', '-', 'i', 'p', False, 0, -1, 0, 0, None, None, None),
    (25, 'text', 11, 10, -1, False, 'b', 'S', True, True, ',', 0, '-', 0, 1009, 'textin', 'textout', 'textrecv', 'textsend', '-', '-', '-', 'i', 'x', False, 0, -1, 0, 100, None, None, None),
    (26, 'oid', 11, 10, 4, True, 'b', 'N', True, True, ',', 0, '-', 0, 1028, 'oidin', 'oidout', 'oidrecv', 'oidsend', '-', '-', '-', 'i', 'p', False, 0, -1, 0, 0, None, None, None),
    (114, 'json', 11, 10, -1, False, 'b', 'U', False, True, ',', 0, '-', 0, 199, 'json_in', 'json_out', 'json_recv', 'json_send', '-', '-', '-', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (199, '_json', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 114, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (700, 'float4', 11, 10, 4, True, 'b', 'N', False, True, ',', 0, '-', 0, 1021, 'float4in', 'float4out', 'float4recv', 'float4send', '-', '-', '-', 'i', 'p', False, 0, -1, 0, 0, None, None, None),
    (701, 'float8', 11, 10, 8, True, 'b', 'N', True, True, ',', 0, '-', 0, 1022, 'float8in', 'float8out', 'float8recv', 'float8send', '-', '-', '-', 'd', 'p', False, 0, -1, 0, 0, None, None, None),
    (705, 'unknown', 11, 10, -2, False, 'p', 'X', False, True, ',', 0, '-', 0, 0, 'unknownin', 'unknownout', 'unknownrecv', 'unknownsend', '-', '-', '-', 'c', 'p', False, 0, -1, 0, 0, None, None, None),
    (1000, '_bool', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 16, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1001, '_bytea', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 17, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1002, '_char', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 18, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1003, '_name', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 19, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 950, None, None, None),
    (1005, '_int2', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 21, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1007, '_int4', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 23, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1009, '_text', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 25, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 100, None, None, None),
    (1014, '_bpchar', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1042, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'bpchartypmodin', 'bpchartypmodout', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 100, None, None, None),
    (1015, '_varchar', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1043, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'varchartypmodin', 'varchartypmodout', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 100, None, None, None),
    (1016, '_int8', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 20, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'd', 'x', False, 0, -1, 0, 0, None, None, None),
    (1021, '_float4', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 700, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1022, '_float8', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 701, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'd', 'x', False, 0, -1, 0, 0, None, None, None),
    (1028, '_oid', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 26, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1042, 'bpchar', 11, 10, -1, False, 'b', 'S', False, True, ',', 0, '-', 0, 1014, 'bpcharin', 'bpcharout', 'bpcharrecv', 'bpcharsend', 'bpchartypmodin', 'bpchartypmodout', '-', 'i', 'x', False, 0, -1, 0, 100, None, None, None),
    (1043, 'varchar', 11, 10, -1, False, 'b', 'S', False, True, ',', 0, '-', 0, 1015, 'varcharin', 'varcharout', 'varcharrecv', 'varcharsend', 'varchartypmodin', 'varchartypmodout', '-', 'i', 'x', False, 0, -1, 0, 100, None, None, None),
    (1082, 'date', 11, 10, 4, True, 'b', 'D', False, True, ',', 0, '-', 0, 1182, 'date_in', 'date_out', 'date_recv', 'date_send', '-', '-', '-', 'i', 'p', False, 0, -1, 0, 0, None, None, None),
    (1083, 'time', 11, 10, 8, True, 'b', 'D', False, True, ',', 0, '-', 0, 1183, 'time_in', 'time_out', 'time_recv', 'time_send', 'timetypmodin', 'timetypmodout', '-', 'd', 'p', False, 0, -1, 0, 0, None, None, None),
    (1114, 'timestamp', 11, 10, 8, True, 'b', 'D', False, True, ',', 0, '-', 0, 1115, 'timestamp_in', 'timestamp_out', 'timestamp_recv', 'timestamp_send', 'timestamptypmodin', 'timestamptypmodout', '-', 'd', 'p', False, 0, -1, 0, 0, None, None, None),
    (1115, '_timestamp', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1114, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'timestamptypmodin', 'timestamptypmodout', 'array_typanalyze', 'd', 'x', False, 0, -1, 0, 0, None, None, None),
    (1182, '_date', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1082, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1183, '_time', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1083, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'timetypmodin', 'timetypmodout', 'array_typanalyze', 'd', 'x', False, 0, -1, 0, 0, None, None, None),
    (1184, 'timestamptz', 11, 10, 8, True, 'b', 'D', True, True, ',', 0, '-', 0, 1185, 'timestamptz_in', 'timestamptz_out', 'timestamptz_recv', 'timestamptz_send', 'timestamptztypmodin', 'timestamptztypmodout', '-', 'd', 'p', False, 0, -1, 0, 0, None, None, None),
    (1185, '_timestamptz', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1184, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'timestamptztypmodin', 'timestamptztypmodout', 'array_typanalyze', 'd', 'x', False, 0, -1, 0, 0, None, None, None),
    (1186, 'interval', 11, 10, 16, False, 'b', 'T', True, True, ',', 0, '-', 0, 1187, 'interval_in', 'interval_out', 'interval_recv', 'interval_send', 'intervaltypmodin', 'intervaltypmodout', '-', 'd', 'p', False, 0, -1, 0, 0, None, None, None),
    (1187, '_interval', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1186, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'intervaltypmodin', 'intervaltypmodout', 'array_typanalyze', 'd', 'x', False, 0, -1, 0, 0, None, None, None),
    (1231, '_numeric', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1700, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'numerictypmodin', 'numerictypmodout', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1266, 'timetz', 11, 10, 12, False, 'b', 'D', False, True, ',', 0, '-', 0, 1270, 'timetz_in', 'timetz_out', 'timetz_recv', 'timetz_send', 'timetztypmodin', 'timetztypmodout', '-', 'd', 'p', False, 0, -1, 0, 0, None, None, None),
    (1270, '_timetz', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1266, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'timetztypmodin', 'timetztypmodout', 'array_typanalyze', 'd', 'x', False, 0, -1, 0, 0, None, None, None),
    (1560, 'bit', 11, 10, -1, False, 'b', 'V', False, True, ',', 0, '-', 0, 1561, 'bit_in', 'bit_out', 'bit_recv', 'bit_send', 'bittypmodin', 'bittypmodout', '-', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1561, '_bit', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1560, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'bittypmodin', 'bittypmodout', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1562, 'varbit', 11, 10, -1, False, 'b', 'V', True, True, ',', 0, '-', 0, 1563, 'varbit_in', 'varbit_out', 'varbit_recv', 'varbit_send', 'varbittypmodin', 'varbittypmodout', '-', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1563, '_varbit', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 1562, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'varbittypmodin', 'varbittypmodout', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (1700, 'numeric', 11, 10, -1, False, 'b', 'N', False, True, ',', 0, '-', 0, 1231, 'numeric_in', 'numeric_out', 'numeric_recv', 'numeric_send', 'numerictypmodin', 'numerictypmodout', '-', 'i', 'm', False, 0, -1, 0, 0, None, None, None),
    (2950, 'uuid', 11, 10, 16, False, 'b', 'U', False, True, ',', 0, '-', 0, 2951, 'uuid_in', 'uuid_out', 'uuid_recv', 'uuid_send', '-', '-', '-', 'c', 'p', False, 0, -1, 0, 0, None, None, None),
    (2951, '_uuid', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 2950, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (3802, 'jsonb', 11, 10, -1, False, 'b', 'U', False, True, ',', 0, 'jsonb_subscript_handler', 0, 3807, 'jsonb_in', 'jsonb_out', 'jsonb_recv', 'jsonb_send', '-', '-', '-', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (3807, '_jsonb', 11, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 3802, 0, 'array_in', 'array_out', 'array_recv', 'array_send', '-', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
    (16388, 'vector', 2200, 10, -1, False, 'b', 'U', False, True, ',', 0, '-', 0, 16389, 'vector_in', 'vector_out', 'vector_recv', 'vector_send', 'vector_typmod_in', '-', '-', 'i', 'e', False, 0, -1, 0, 0, None, None, None),
    (16389, '_vector', 2200, 10, -1, False, 'b', 'A', False, True, ',', 0, 'array_subscript_handler', 16388, 0, 'array_in', 'array_out', 'array_recv', 'array_send', 'vector_typmod_in', '-', 'array_typanalyze', 'i', 'x', False, 0, -1, 0, 0, None, None, None),
)
# fmt: on
