Class Spike.Q2 Extends %RegisteredObject
{

ClassMethod Run()
{
    set verdict = "INCONCLUSIVE", note = "probe did not complete"
    set cls = "", dl = "", il = "", found = -1

    write !,"Q2.1 create DDL table SQLUser.SpikeQ2",!
    set rs = ##class(%SQL.Statement).%ExecDirect(,"DROP TABLE SQLUser.SpikeQ2")
    set rs = ##class(%SQL.Statement).%ExecDirect(,"CREATE TABLE SQLUser.SpikeQ2 (id INT PRIMARY KEY, name VARCHAR(50))")
    if rs.%SQLCODE < 0 {
        write "  CREATE failed: SQLCODE=",rs.%SQLCODE," ",rs.%Message,!
        write !,"Q2 VERDICT: INCONCLUSIVE -- could not create test table",!
        quit
    }
    write "  created",!
    set rs = ##class(%SQL.Statement).%ExecDirect(,"INSERT INTO SQLUser.SpikeQ2 (id,name) VALUES (1,'alpha')")
    if rs.%SQLCODE < 0 {
        write "  INSERT failed: SQLCODE=",rs.%SQLCODE," ",rs.%Message,!
        write !,"Q2 VERDICT: INCONCLUSIVE -- could not insert test row",!
        quit
    }
    write "  inserted 1 row",!

    write !,"Q2.2 resolve backing global via %Dictionary.CompiledStorage",!
    set q = "SELECT c.Name AS cls, s.DataLocation AS dl, s.IndexLocation AS il "
    set q = q_"FROM %Dictionary.CompiledClass c "
    set q = q_"LEFT JOIN %Dictionary.CompiledStorage s ON s.parent = c.Name "
    set q = q_"WHERE c.SqlSchemaName = ? AND c.SqlTableName = ?"
    set rs = ##class(%SQL.Statement).%ExecDirect(,q,"SQLUser","SpikeQ2")
    if rs.%SQLCODE < 0 {
        write "  query failed: SQLCODE=",rs.%SQLCODE," ",rs.%Message,!
        write !,"Q2 VERDICT: INCONCLUSIVE -- storage lookup query itself failed",!
        quit
    }
    while rs.%Next() {
        set cls = rs.%Get("cls"), dl = rs.%Get("dl"), il = rs.%Get("il")
        write "  class=",cls,"  data=",dl,"  index=",il,!
    }
    if cls = "" { write "  no class projection found",! }
    if dl = "" { write "  no DataLocation returned",! }

    write !,"Q2.3 verify the resolved global actually holds the row",!
    if dl '= "" {
        try {
            set found = $data(@dl)
        } catch e {
            write "  indirection on '",dl,"' failed: ",e.DisplayString(),!
            set found = -1
        }
        write "  $DATA(",dl,") = ",found,!
        if found > 0 {
            set sub = $order(@dl@(""))
            write "  first subscript: ",sub,!
            if sub '= "" { write "  value: ",$listtostring($get(@dl@(sub)),"|"),! }
        }
    }

    write !,"Q2.4 check the legacy inference ^SQLUser.SpikeQ2D",!
    set naive = "^SQLUser.SpikeQ2D", naiveFound = -1
    try {
        set naiveFound = $data(@naive)
    } catch e {
        set naiveFound = -1
    }
    write "  $DATA(",naive,") = ",naiveFound,!
    if (dl '= "") && (dl '= naive) {
        write "  resolved global DIFFERS from the inferred name",!
        if naiveFound = 0 {
            write "  >> INFERENCE IS UNSAFE: it names a global that does not exist",!
        }
    }
    if dl = naive {
        write "  this table did NOT use hashed storage -- inference happens to match here",!
    }

    if (dl '= "") && (found > 0) {
        set verdict = "PASS", note = "resolved "_dl_" and the row was found there"
    } elseif (dl '= "") && (found = 0) {
        set verdict = "FAIL", note = "resolved "_dl_" but no data present at that global"
    } elseif cls '= "" {
        set verdict = "FAIL", note = "class "_cls_" projected but DataLocation was empty"
    } else {
        set verdict = "FAIL", note = "no class projection resolved for a DDL-created table"
    }

    if %%KEEP%% = 0 {
        set rs = ##class(%SQL.Statement).%ExecDirect(,"DROP TABLE SQLUser.SpikeQ2")
        write !,"  (test table dropped)",!
    }
    write !,"Q2 VERDICT: ",verdict," -- ",note,!
    quit
}

}
