/// T011a follow-up: build the `%INLIST` match set inside IRIS instead of
/// encoding $LIST bytes in Python.
///
/// The shipped implementation encodes the $LIST wire format itself. That format
/// is undocumented, so this probe asks whether the supported route works
/// instead: pass the elements as one ordinary string parameter and let
/// ObjectScript assemble the list with $LISTBUILD.
///
/// Decides three things:
///   R1  does `%INLIST <SqlProc>(?)` PREPARE?  (Describe needs it to)
///   R2  does it return the same rows as a bound $LIST?
///   R3  what does the extra call cost per query?
Class Spike.T011aProc Extends %RegisteredObject
{

Parameter VIEW = "pg_catalog.pg_namespace";

/// Build a %List from a length-prefixed encoding: `<n>:<n chars>` repeated,
/// with n = -1 for a NULL element. No delimiter, so no escaping and no value
/// can be misread — which is what rules out $LISTFROMSTRING.
ClassMethod PgArray(encoded As %String) As %List [ SqlName = PG_ARRAY, SqlProc ]
{
	set list = "", pos = 1, len = $length(encoded)
	while pos <= len {
		set colon = $find(encoded, ":", pos)
		if colon = 0 { quit }
		set count = $extract(encoded, pos, colon - 2)
		if count = -1 {
			set list = list _ $listbuild()
			set pos = colon
			continue
		}
		set list = list _ $listbuild($extract(encoded, colon, colon + count - 1))
		set pos = colon + count
	}
	quit list
}

ClassMethod Run()
{
	write !,"=== T011a follow-up: SqlProc-built match set ===",!

	do ..R0()
	do ..R1()
	do ..R2()
	do ..R3()

	write !,"=== end ===",!
	quit
}

/// Sanity: the encoder/decoder round-trips before any SQL is involved.
ClassMethod R0()
{
	write !,"R0  decode round-trip",!
	set cases = $listbuild(
		"6:public10:pg_catalog",
		"6:public",
		"",
		"-1:",
		"0:",
		"5:a,b,c")
	for i = 1:1:$listlength(cases) {
		set enc = $list(cases, i)
		set out = ..PgArray(enc)
		write "  ",$select(enc="":"(empty)",1:enc)," -> ",$listlength(out)," elements: "
		for j = 1:1:$listlength(out) { write "[",$listget(out, j),"]" }
		write !
	}
	quit
}

ClassMethod R1()
{
	write !,"R1  preparability",!
	set shapes = $listbuild(
		"%INLIST Spike.PG_ARRAY(?)",
		"%INLIST ?")
	for i = 1:1:$listlength(shapes) {
		set shape = $list(shapes, i)
		set sql = "SELECT nspname FROM " _ ..#VIEW _ " WHERE nspname " _ shape
		set stmt = ##class(%SQL.Statement).%New()
		set sc = stmt.%Prepare(sql)
		if $system.Status.IsError(sc) {
			write "  ",shape," -> PREPARE FAILED: ",$system.Status.GetErrorText(sc),!
		} else {
			set count = "?"
			try { set count = stmt.%Metadata.parameterCount } catch e { }
			write "  ",shape," -> PREPARE OK, parameterCount=",count,!
		}
	}
	quit
}

ClassMethod R2()
{
	write !,"R2  same rows as a bound $LIST",!
	set sql = "SELECT nspname FROM " _ ..#VIEW _ " WHERE nspname %INLIST Spike.PG_ARRAY(?)"
	do ..Show(sql, "6:public", "one value")
	do ..Show(sql, "6:public10:pg_catalog", "two values")
	do ..Show(sql, "12:nosuchschema", "no match")
	do ..Show(sql, "", "empty array")
	do ..Show(sql, "-1:", "array of one NULL")
	do ..Show(sql, "8:has,comma", "value containing a comma")

	set neg = "SELECT nspname FROM " _ ..#VIEW _ " WHERE NOT (nspname %INLIST Spike.PG_ARRAY(?))"
	do ..Show(neg, "6:public", "negated")

	set num = "SELECT nspname FROM " _ ..#VIEW _ " WHERE oid %INLIST Spike.PG_ARRAY(?)"
	do ..Show(num, "4:2200", "numeric column, string element")
	quit
}

ClassMethod Show(sql As %String, arg As %String, label As %String)
{
	set stmt = ##class(%SQL.Statement).%New()
	set sc = stmt.%Prepare(sql)
	if $system.Status.IsError(sc) {
		write "  ",label,": PREPARE FAILED ",$system.Status.GetErrorText(sc),!
		quit
	}
	set rs = stmt.%Execute(arg)
	if rs.%SQLCODE < 0 {
		write "  ",label,": SQLCODE ",rs.%SQLCODE," ",rs.%Message,!
		quit
	}
	set n = 0, vals = ""
	while rs.%Next() {
		set n = n + 1
		if n < 6 { set vals = vals _ $select(vals="":"", 1:", ") _ rs.%GetData(1) }
	}
	write "  ",label,": ",n," rows [",vals,"]",!
	quit
}

ClassMethod R3()
{
	write !,"R3  cost of the extra call (1000 executions each)",!
	set direct = "SELECT nspname FROM " _ ..#VIEW _ " WHERE nspname %INLIST ?"
	set viaproc = "SELECT nspname FROM " _ ..#VIEW _ " WHERE nspname %INLIST Spike.PG_ARRAY(?)"

	set d = ..Time(direct, $listbuild("public"), 1000)
	set p = ..Time(viaproc, "6:public", 1000)
	write "  bound $LIST      : ",$fnumber(d, "", 3)," s  (",$fnumber(d, "", 4)*1000," ms/query)",!
	write "  via Spike.PG_ARRAY: ",$fnumber(p, "", 3)," s  (",$fnumber(p, "", 4)*1000," ms/query)",!
	write "  overhead         : ",$fnumber((p - d) / 1000 * 1000, "", 4)," ms/query",!
	quit
}

ClassMethod Time(sql As %String, arg, iterations As %Integer) As %Numeric
{
	set stmt = ##class(%SQL.Statement).%New()
	do stmt.%Prepare(sql)
	set start = $zhorolog
	for i = 1:1:iterations {
		set rs = stmt.%Execute(arg)
		while rs.%Next() { }
	}
	quit $zhorolog - start
}

}
