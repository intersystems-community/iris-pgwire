/// T011a spike: can IRIS *prepare* a variable-length membership test with a
/// single bound parameter?
///
/// The blocker is at Prepare/Describe, not Execute: the extended query protocol
/// describes a statement before any value is bound, so `= ANY(?)` has to be
/// preparable on its own. Value substitution at Execute can never help.
///
/// Probes, in order of what they decide:
///   P1  `= ANY(?)`            -- the current failure; record its exact SQLCODE
///   P2  `%INLIST ?`           -- the candidate; preparable at all?
///   P3  `%INLIST ?` executed  -- one value, two values, empty list, non-list
///   P4  `IN (?)`              -- option 1's baseline (single-element rewrite)
///   P5  `%INLIST` on a base table, not just a view
///   P6  `%INLIST ? SIZE ((n))` -- the documented planner hint
///   P7  parameter count reported by prepared metadata for each shape
///   P8  NULL handling in the matched column
Class Spike.T011a Extends %RegisteredObject
{

/// A view installed by feature 044. Membership against nspname is the exact
/// query Prisma issues and the one that fails today.
Parameter VIEWQ = "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname ";

Parameter BASEQ = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME ";

ClassMethod Run()
{
	write !,"=== T011a: preparability of variable-length membership ===",!

	do ..P1()
	set p2 = ..P2()
	if p2 { do ..P3() }
	do ..P4()
	do ..P5()
	do ..P6()
	do ..P7()
	do ..P8()

	write !,"=== end ===",!
	quit
}

/// Prepare `sql`, returning 1 on success. Writes the SQLCODE / message either way.
ClassMethod Prep(label As %String, sql As %String, ByRef stmt) As %Boolean
{
	write !,label,!
	write "  SQL: ",sql,!
	set stmt = ##class(%SQL.Statement).%New()
	set ok = 0
	try {
		set sc = stmt.%Prepare(sql)
		if $system.Status.IsError(sc) {
			write "  PREPARE FAILED: ",$system.Status.GetErrorText(sc),!
		} else {
			write "  PREPARE OK",!
			set ok = 1
		}
	} catch e {
		write "  PREPARE THREW: ",e.DisplayString(),!
	}
	quit ok
}

/// Execute a prepared statement with one argument and report rows.
ClassMethod Exec(label As %String, stmt As %SQL.Statement, arg)
{
	write "  ",label,!
	try {
		set rs = stmt.%Execute(arg)
		if rs.%SQLCODE < 0 {
			write "    SQLCODE ",rs.%SQLCODE," ",rs.%Message,!
			quit
		}
		set n = 0, vals = ""
		while rs.%Next() {
			set n = n + 1
			if n < 6 { set vals = vals _ $select(vals="":"", 1:", ") _ rs.%GetData(1) }
		}
		write "    rows=",n," [",vals,"] SQLCODE=",rs.%SQLCODE,!
	} catch e {
		write "    THREW: ",e.DisplayString(),!
	}
	quit
}

ClassMethod P1()
{
	do ..Prep("P1  baseline: = ANY(?)", ..#VIEWQ_"= ANY(?)", .stmt)
	quit
}

ClassMethod P2() As %Boolean
{
	quit ..Prep("P2  candidate: %INLIST ?", ..#VIEWQ_"%INLIST ?", .stmt)
}

ClassMethod P3()
{
	write !,"P3  %INLIST ? executed with bound values",!
	if '..Prep("    (re-prepare)", ..#VIEWQ_"%INLIST ?", .stmt) { quit }
	do ..Exec("one value  $LB(""public"")", stmt, $listbuild("public"))
	do ..Exec("two values $LB(""public"",""pg_catalog"")", stmt, $listbuild("public","pg_catalog"))
	do ..Exec("no match   $LB(""nosuchschema"")", stmt, $listbuild("nosuchschema"))
	do ..Exec("empty list $LB()", stmt, $listbuild())
	do ..Exec("empty str  """"", stmt, "")
	do ..Exec("plain str  ""public"" (not a $LIST)", stmt, "public")
	quit
}

ClassMethod P4()
{
	do ..Prep("P4  option 1 baseline: IN (?)", ..#VIEWQ_"IN (?)", .stmt)
	quit
}

ClassMethod P5()
{
	if ..Prep("P5  %INLIST over a base table (INFORMATION_SCHEMA.TABLES)", ..#BASEQ_"%INLIST ?", .stmt) {
		do ..Exec("two values", stmt, $listbuild("customer","orderline"))
	}
	quit
}

ClassMethod P6()
{
	if ..Prep("P6  planner hint: %INLIST ? SIZE ((10))", ..#VIEWQ_"%INLIST ? SIZE ((10))", .stmt) {
		do ..Exec("one value", stmt, $listbuild("public"))
	}
	quit
}

ClassMethod P7()
{
	write !,"P7  parameter count in prepared metadata",!
	set shapes = $listbuild("%INLIST ?", "IN (?)", "= ?", "%INLIST ? SIZE ((10))")
	for i = 1:1:$listlength(shapes) {
		set shape = $list(shapes, i)
		set stmt = ##class(%SQL.Statement).%New()
		set sc = stmt.%Prepare(..#VIEWQ_shape)
		if $system.Status.IsError(sc) {
			write "  ",shape," -> not preparable",!
			continue
		}
		set count = "?"
		try { set count = stmt.%Metadata.parameterCount } catch e { set count = "unavailable: "_e.DisplayString() }
		write "  ",shape," -> parameterCount=",count,!
	}
	quit
}

ClassMethod P8()
{
	write !,"P8  NULL in the matched column",!
	write "    docs: the match expression cannot return NULL fields (SQLCODE -400)",!
	set sql = "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE %INLIST ?"
	if ..Prep("    nullable-ish column", sql, .stmt) {
		do ..Exec("BASE TABLE + VIEW", stmt, $listbuild("BASE TABLE","VIEW"))
	}
	quit
}

}
