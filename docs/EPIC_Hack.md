**rch Hack-a-thon**

Mark Hanson added Nicholai Mitchko and 11 others to the chat.

Mark Hanson

 added 

Nicholai Mitchko

 and 11 others to the chat.

Mark Hanson changed the group name to Epic Vector Search Hack-a-thon.

Mark Hanson

 changed the group name to Epic Vector Search Hack-a-thon.

Setting up this channel to coordinate our f\... by Mark Hanson

Mark Hanson

7/30 5:10 PM

Setting up this channel to coordinate our for the Epic Hack-a-thon
around IRIS Vector search.

 

My expectation is for hack-a-thon Epic will be running logic from IRIS
that will provide an API to allow calling out to an IRIS Vector search
instance to either do vector search or to insert/update/delete vectors
from the instance (

Jose

 

Ruperez

 will verify this). Their current solution for this is Elasticsearch and
we want to show our full SQL capabilities off to good advantage compared
to this project.

 

My initial take on what we need to deliver for this:

- IRIS instance running code branch of our choosing so we can push new
  dev changes as needed that does vector search in cloud, would be good
  to understand latency between making a core product change and how
  long before we can have this on a cloud instance.

- Embedding model that we can call from the cloud instance, suggest we
  start with OpenAI as we have an interface to this already and we know
  it supports high load?

- Ability to create new tables easily, drop them, alter them as needed
  by hack-a-thon, expect the current cloud SQL web interface will be
  sufficient for this.

- Ability to insert at a high data rate text (or embeddings if Epic
  wishes to transform text to embedding on the client) along with
  structured column fields into these tables

- HNSW index on the vectors in this table so we can do ANN matching

- Ability to query that tables via SQL over REST (as query needs to be
  stateless so we can not use JDBC/ODBC)

- Client logic to call this REST interface from objectScript for query
  and ingest

- Measurements of Elasticsearch showing its performance at ingest and
  comparison with IRIS vector search doing the same operations so know
  where we stand from a performance perspective.

- Ability to run tools like %SYS.MONLBL on the cloud instance or \'perf
  top\' so we can measure performance hot spots

Open question for Epic that 

Jose

 

Ruperez

 will get answered:

- **Most important** : Is the client code going to be run from an Epic
  IRIS instance, so do they want an API in IRIS they can call to do the
  SQL/vector search against our cloud instance? If not from IRIS where
  will it be called from, what language should the API be provided in? 

- Does cloud instance need to turn text to embedding or does Epic wish
  to do this part of the pipeline themselves? I think our solution looks
  better if we take care of generating the embeddings (and we have logic
  to do this already), but we should ask.

- For hack-a-thon we plan on modifying table definitions in the IRIS
  cloud instance via a web based UI. We can support these via client
  API, but assume the web UI is good enough to start with.

- What is an example of data Epic wishes to store? We are assuming it is
  text along with some structured field data, if they want us to support
  say parsing pdf we can but would want to know up front. Can they
  provide any examples of expected data they will want to insert?

Current tasks are:

- Alex

>  
>
> Afanasiev
>
>  - Client logic to call REST endpoint from IRIS, should be similar to
> %SQL.Statement, need to put this into IPM module so we can provide
> this to Epic to be loaded onto their IRIS instance. Can we build this
> without using Python to avoid dependency on python logic and overhead
> of calling this? If we need to use python we could as long as Epic is
> okay having python installed and using embedded python from IRIS.

- Alex

>  
>
> Afanasiev
>
>  - Client logic to insert a new vector/embedding into the cloud
> instance. Can also model after %SQL.Statement using same endpoint as
> this is just a different SQL statement (INSERT not SELECT), but may
> want to look if we should specialize for this case to improve
> performance after we get to benchmarking.

- Louis

>  
>
> Kabelka
>
>  
>
> Zelong
>
>  
>
> Wang
>
>  - Benchmark query performance. Straight vector search on a large
> table, also vector search combined with other restrictions on the
> table of varying selectivity e.g. 0.5, 0.25, 0.125,\.... We should
> ensure we have index on all other columns we may be restricting the
> query on. Test framework needs to be multiprocess/threaded to simulate
> actual load. Benchmark needs to use the API we will provide to Epic so
> we are measuring what they will see.

- Louis

>  
>
> Kabelka
>
>  
>
> Zelong
>
>  
>
> Wang
>
>  - Benchmark insert performance. Multiprocess framework, for N jobs
> max insert per second. Assume mostly insert and low update rate.

- Suprateem

>  
>
> Banerjee
>
>  - Figure out ElasticSearch examples so we can stand up an
> ElasticSearch server with the same dataset and benchmark between the
> two.

Mentors listed below will help with any questions you have:

- Boya

>  
>
> Song
>
>  - HNSW index developer, vector search expert

- Dave

>  
>
> VanDeGriek
>
>  - IRIS SQL expert, also deferred indexing developer

- Steven

>  
>
> Lubars
>
>  - IRIS cloud instance setup

- Ray

>  
>
> Wright
>
>  - Performance testing, has done vector search benchmarking before

- Benjamin

>  
>
> De
>
>  
>
> Boe
>
>  - SQL product manager

I am sure this list will morph over time, but hopefully it provides a
starting point. The plan is for 

Nicholai

 

Mitchko

 to project manage this work once he is back and I and my team will
provide technical input and any development work needed.

![🔥](media/image1.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Fire reactions.

2

1 bongocat-code reaction.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Suprateem   Banerjee  I did a quick look at\... by Mark Hanson

Mark Hanson

7/30 5:13 PM

Suprateem

 

Banerjee

 I did a quick look at ACORN-1 for Elasticsearch and we could add this
to our HNSW search if it becomes an important enough feature for product
management to green light this, it looks like a simple enough extension
of regular HNSW search and I see they add in neighbors of neighbors in
order to avoid making the neighborhoods too small to be useful as they
are filtering at the neighbor level. However right now there are no
plans for this work.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Attached is logic SteveL provided (written \... by Mark Hanson, has an
attachment.

Mark Hanson

7/30 5:23 PM

Attached is logic SteveL provided (written by Jeffrey Parker\'s group)
that is used to test IRIS SQL cloud and demonstrates the REST API that
IRIS SQL cloud already supports. As we already have this REST based API
it seems like a good starting point.

 

Docs on using IRIS Vector search
: [[https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_vecsearch]{.underline}](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_vecsearch)

Docs on VECTOR datatype in SQL
: [[https://usconfluence.iscinternal.com/display/SPMI/Vector+SQL+datatype]{.underline}](https://usconfluence.iscinternal.com/display/SPMI/Vector+SQL+datatype)

 

Work that is completing shortly is deferred indexing that allows us to
ingest rows into a table quickly and defer generation of embeddings to
be done by a daemon that is done outside of the original transaction.
This may be required if we want to handle generating the embeddings
ourselves. [[https://usconfluence.iscinternal.com/display/SQL/Deferred+Filing+of+Indices+and+Computed+Fields]{.underline}](https://usconfluence.iscinternal.com/display/SQL/Deferred+Filing+of+Indices+and+Computed+Fields)

Recent builds from //projects/sql branch has this working, and if we
need this for the hack-a-thon we should be able to get this prerelease
code in the cloud. Ask 

Dave

 

VanDeGriek

 for any questions on this.

 

Also work in progress is improved HNSW neighborhood data structure
(about 10-15% performance improvement) and better handling for duplicate
vectors which has been very common in practice and avoids poor recall
behavior when datasets have large numbers of duplicates. 

Boya

 

Song

 can provide details of this if needed.

**test_sql.py**

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

July 31

That Link ACORN-1 optimization sounds hig\... by Benjamin De Boe

Benjamin De Boe

7/31 2:19 AM

That [[ACORN-1]{.underline}](https://www.elastic.co/search-labs/blog/filtered-hnsw-knn-search) optimization
sounds highly relevant, also for the kind of challenges our early
adopters SerenityGPT and BioStrand have reported (despite our best
intentions, the tipping point between using the ANN index and a regular
one is a bit of a cliff). Worth 

Boya

 

Song

 taking a look and at least assess if any changes to the graph structure
are warranted, such that we don\'t need to change it more than once
(between 25.2 and 25.3).

[![Url Preview for Filtered HNSW & kNN search: Making searches faster -
Elasticsearch Labs](media/image3.gif){width="7.638888888888889e-3in"
height="7.638888888888889e-3in"}](https://www.elastic.co/search-labs/blog/filtered-hnsw-knn-search)

[**Filtered HNSW & kNN search: Making searches faster - Elasticsearch
Labs**](https://www.elastic.co/search-labs/blog/filtered-hnsw-knn-search)

[Explore the improvements we have made for HNSW vector search in Apache
Lucene through our ACORN-1 algorithm
implementation.](https://www.elastic.co/search-labs/blog/filtered-hnsw-knn-search)

[www.elastic.co](https://www.elastic.co/search-labs/blog/filtered-hnsw-knn-search)

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Benjamin De Boe added Thomas Dyar to the chat and shared all chat
history.

Benjamin De Boe

 added 

Thomas Dyar

 to the chat and shared all chat history.

when is the hack-a-thon scheduled to take p\... by Ray Wright

Ray Wright

7/31 4:12 AM

when is the hack-a-thon scheduled to take place?

Sep 8 or 9, I believe by Benjamin De Boe

Benjamin De Boe

7/31 4:23 AM

Sep 8 or 9, I believe

Elastic also has advanced quantization tech\... by Suprateem Banerjee

Suprateem Banerjee

7/31 5:04 AM

Elastic also has advanced quantization techniques we currently lack.
They default to a int8 quantization for vector storage (letting them
store more vectors in memory), and implement a Better Binary
Quantization (BBQ) algorithm as a preprocessing step to accelerate and
even improve their HNSW performance. Our system, while resilient (we
persist the graph on disk, unlike Elastic), lacks any quantization
capabilities (as mentioned by Mark yesterday) which would lead to slower
performance due to less vectors that can be cached in memory.\
\
Curious to understand how much of a heavy lift is implementing
quantization, since all major vector store players in the market have
quantization capabilites (Weaviate, Qdrant, Milvus, Elastic, and so on).

Basic Scalar Quantization would probably be\... by Benjamin De Boe

Benjamin De Boe

7/31 5:59 AM

Basic Scalar Quantization would probably be straightforward, but
anything smarter that needs to adapt to the dataset is likely to be both
complex to implement and will further slow down our index build. We
don\'t have a ton of time to prepare for the hackathon and want to limit
risk, so we\'d need to be very confident about benefits and being able
to pull it off in time. 

That said, we can reduce risk / experiment by looking at this as an
independent preprocessing step and just build it out into a separate
column with its own index such that we can measure the benefits without
touching our HNSW logic.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Benjamin De Boe added Bob Kuszewski to the chat and shared all chat
history.

Benjamin De Boe

 added 

Bob Kuszewski

 to the chat and shared all chat history.

Begin Reference, That ACORN-1 optimization \... by Boya Song

Boya Song

7/31 8:40 AM

Benjamin De Boe7/31/25 2:19 AM

That ACORN-1 optimization sounds highly relevant, also for the kind of
challenges our early adopters SerenityGPT and BioStrand have reported
(despite our best intentions, the tipping point between using...

We only need to modify the search function for this, so no need to
change the index storage! The biggest task would be figuring out how to
pass the filtering condition to the HNSW search; the most ideal
interface I can think of is passing the pointer to a binary function
that takes %ID as input and returns 1/0 to indicate if row with %ID
satisfies the condition or not.

Begin Reference, We only need to modify the\... by Mark Hanson

Mark Hanson

7/31 10:15 AM

Boya Song7/31/25 8:40 AM

We only need to modify the search function for this, so no need to
change the index storage! The biggest task would be figuring out how to
pass the filtering condition to the HNSW search; the most ideal
interface I can think of is passing the pointer to a binary function
that takes %ID as input and...

I was thinking along these lines too, we do not need to put the other
fields in the HNSW as we can efficiently read them from the master map.
We could get SQL to build a function that given an ID performs the
filter that we can call from HNSW search logic, so then we only need to
pass into HNSW the name of this lambda to call.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Like reactions.

2

that could be part of the CQ, and take adva\... by Benjamin De Boe

Benjamin De Boe

7/31 10:19 AM

that could be part of the CQ, and take advantage of other indices if
that\'s worth avoiding the master map read

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Like reactions.

2

exactly! by Boya Song

Boya Song

7/31 10:25 AM

exactly!

The current RAG landscape is also shifting \... by Suprateem Banerjee,
has an attachment.

Suprateem Banerjee

7/31 12:01 PM

The current RAG landscape is also shifting towards Multi Vector
Retrieval capabilities. Currently only a few vector stores support it
natively (notably popular vector stores like Pinecone and others such as
Elastic does not), while vector stores like Weaviate offer alternatives
such as multi vector compression into a single vector using MUVERA
before indexing compressed vectors.

 

If we develop capabilities in the multi vector space for our vector
store, it could be a prominent differentiator against competitors in the
space. Sharing a ChatGPT Deep Research that I generated and read through
this morning. It is pretty comprehensive for the subject matter
(encompasses most things I already know on the subject). I expect this
to be a heavier lift that other capabilities, but let me know your
thoughts and in what ways we can support multi vector retrieval.

**Multi-Vector Retrieval\_ Methods and Vector Store Support.pdf**

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Begin Reference, Attached is logic SteveL p\... by Jose Ruperez

Jose Ruperez

7/31 2:19 PM

Mark Hanson7/30/25 5:23 PM

Attached is logic SteveL provided (written by Jeffrey Parker\'s group)
that is used to test IRIS SQL cloud and demonstrates the REST API that
IRIS SQL cloud already supports. As we already have this REST based API
it seems like a good starting point. Docs on using IRIS Vector search :
https://do...

It looks all SQL, no REST api

I don\'t know the REST path in our API gatew\... by Steven Lubars

Steven Lubars

7/31 2:44 PM

I don\'t know the REST path in our API gateway (the \"base_url\"
referenced in the calls), but it\'s not complicated - just a body with a
couple of connection-related fields and a sql field - let me find an
example from the last time I did a query by hand from the command line

  curl -H \"Authorization:eyJraWQiOiJWN0dqWk\... by Steven Lubars

Steven Lubars

7/31 2:45 PM

Edited

 

curl -H
\"Authorization:eyJraWQiOiJWN0dqWklDZlE5em85MEVSSG5Jbk5IVVlWNGVPNEgyTDVHSmN5bW1TMExzPSIsImFsZyI6IlJTMjU2In0.eyJzdWIiOiI4ZWMyMWY0OC0zNzcyLTQ4MDktOTQ2NC1kNWU2NDM1ZDEzZTkiLCJhdWQiOiIxZ28wbGk4cmdsOW85bHZmZjR1OTVvaW5wNCIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJldmVudF9pZCI6IjU0Yjk4ZmExLTMwNmMtNGFkZC04ZjNmLWVkNjFhZjk2NGEwOCIsInRva2VuX3VzZSI6ImlkIiwiYXV0aF90aW1lIjoxNjM5NDEzMTQzLCJpc3MiOiJodHRwczpcL1wvY29nbml0by1pZHAudXMtZWFzdC0yLmFtYXpvbmF3cy5jb21cL3VzLWVhc3QtMl9QMmxGTlJadEciLCJjb2duaXRvOnVzZXJuYW1lIjoic2x1YmFycyIsImV4cCI6MTYzOTQxNjc0MywiaWF0IjoxNjM5NDEzMTQzLCJlbWFpbCI6InNsdWJhcnNAaW50ZXJzeXN0ZW1zLmNvbSJ9.FtnwQTYNoQ7vYLFrU6p5tlbLnbf-42y8nficCt5ESMfvmoKi1pWNLf3gjlkSwWIJtAaZmHUfElNLsFMjXI_wnV4BNNKNBuAZqTRYm4uHvVWB4t-vRISIDT0E-AbiKhLFG_ZBvNwOBF_ZH1_9C4mc3EqPIrgYDeRbNMhOfazKm4YJVYI_Ml5X_iJaRi3TdvZyFiO1ek3BExXuHfGOVWSGgYToKQjlX4UKNvgqaPQotGYYbkCfc-R_aj0vZXHhIzKCjWbzuBF0ilU-0-ybfuIg61fyQbYmgLrOhazc3Ux6oB9BKeozs0lgCdhH3ZAHwH8UZMtJdmh3td8pFO7RXPn-FA\" -XPOST
\"[[https://zof82cba0d.execute-api.us-east-2.amazonaws.com/sll/sql/query\"]{.underline}](https://zof82cba0d.execute-api.us-east-2.amazonaws.com/sll/sql/query%22) -d
\'{\"body\":\"{\\\"connection\\\":{\\\"host\\\":\\\"192.168.90.204\\\"},\\\"sql\\\":\\\"LOAD
DATA FROM FILE \'/tmp/sample.csv\' INTO foo USING
{\\\\\\\"from\\\\\\\":{\\\\\\\"file\\\\\\\":{\\\\\\\"header\\\\\\\":\\\\\\\"1\\\\\\\"}}}\\\"}\"}\'

 

Thank you by Jose Ruperez

Jose Ruperez

7/31 2:55 PM

Thank you

Steven   Lubars  and I had a conversation a\... by Mark Hanson

Mark Hanson

7/31 2:57 PM

Steven

 

Lubars

 and I had a conversation about what cloud environment we can create for
this work. He is going to explore the options (perhaps a feature
environment) to see what will work best as Epic will be accessing this
from Epic IP addresses. I will create a project branch in Perforce based
off //iris/latest to we can control what core IRIS code goes into this
environment and will update everyone when this is done.

 

We discussed the current REST API and the overhead it may have, it
sounds like writing a REST service in IRIS and directing the REST
requests at this (via the CSP gateway) may be quite a bit more
performant as currently for every REST request we initiate a new JDBC
connection and then have to copy data over between JDBC and the REST
response. However we should get things working ASAP and we can try out
improved interfaces once we have proved the basic concept.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

4 Like reactions.

4

As I mentioned to Alex   Afanasiev  separa\... by Mark Hanson

Mark Hanson

7/31 3:00 PM

As I mentioned to 

Alex

 

Afanasiev

 separately to start with we can use vanilla IRIS SQL cloud environments
and see how far we get with this, so no need to wait for any hack-a-thon
specific environments.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

3 Like reactions.

3

Do we have a good dataset with a large volu\... by Suprateem Banerjee

Suprateem Banerjee

7/31 3:04 PM

Do we have a good dataset with a large volume of precomputed vectors?
I\'d imagine for a benchmark we would want \>1M rows. Curious if we
already have something we can work with. Otherwise we can look for
something on HF.

This is what Ray used for his vector search\... by Louis Kabelka

Louis Kabelka

7/31 3:07 PM

This is what Ray used for his vector search benchmarking - 500k
rows: [[https://huggingface.co/datasets/Cohere/wikipedia-22-12-simple-embeddings]{.underline}](https://huggingface.co/datasets/Cohere/wikipedia-22-12-simple-embeddings)

I initially thought I\'d look at the MyChart\... by Suprateem Banerjee

Suprateem Banerjee

7/31 3:08 PM

I initially thought I\'d look at the MyChart docs itself, but it\'s far
too limited for any real benchmarking. Can be used for demoing
though. [[https://www.mychart.org/Help?tab=faq]{.underline}](https://www.mychart.org/Help?tab=faq)

[![Url Preview for Help \|
MyChart](media/image3.gif){width="7.638888888888889e-3in"
height="7.638888888888889e-3in"}](https://www.mychart.org/Help?tab=faq)

[**Help \| MyChart**](https://www.mychart.org/Help?tab=faq)

[How do I sign up for MyChart? Can I link two accounts? And other
frequently asked questions about
MyChart.](https://www.mychart.org/Help?tab=faq)

[www.mychart.org](https://www.mychart.org/Help?tab=faq)

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

This is a good dataset too. Lots of fields \... by Suprateem Banerjee

Suprateem Banerjee

7/31 3:16 PM

This is a good dataset too. Lots of fields to filter and experiment with
indices. [[https://huggingface.co/datasets/Cohere/wikipedia-22-12-en-embeddings]{.underline}](https://huggingface.co/datasets/Cohere/wikipedia-22-12-en-embeddings)

[![Url Preview for Cohere/wikipedia-22-12-en-embeddings · Datasets at
Hugging Face](media/image3.gif){width="7.638888888888889e-3in"
height="7.638888888888889e-3in"}](https://huggingface.co/datasets/Cohere/wikipedia-22-12-en-embeddings)

[**Cohere/wikipedia-22-12-en-embeddings · Datasets at Hugging
Face**](https://huggingface.co/datasets/Cohere/wikipedia-22-12-en-embeddings)

[We're on a journey to advance and democratize artificial intelligence
through open source and open
science.](https://huggingface.co/datasets/Cohere/wikipedia-22-12-en-embeddings)

[huggingface.co](https://huggingface.co/datasets/Cohere/wikipedia-22-12-en-embeddings)

![❤️](media/image4.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Heart reaction.

Question from my team:  What do we know abo\... by Steven Lubars

Steven Lubars

7/31 3:36 PM

Question from my team:  What do we know about machine sizing - will one
of our current t-shirt sizes suffice?  Or do we need to work backwards
from performance expectations?

I suppose we can start with the biggest t-s\... by Jose Ruperez

Jose Ruperez

7/31 3:40 PM

I suppose we can start with the biggest t-shirt size you have and go
from there. Once we test performance a bit we can decide if a bigger one
is needed. what do you think, Mark ?

For any who are interested, here\'s the writ\... by Randy Pallotta, has
an attachment.

Randy Pallotta

7/31 3:59 PM

For any who are interested, here\'s the write up for the POC

**Vector Search - Proof of Concept Specification Second Draft 2.docx**

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

To utilize are x-large size to its fullest,\... by Steven Lubars

Steven Lubars

7/31 4:14 PM

To utilize are x-large size to its fullest, we\'ll want to crank up
storage specs as well.  I don\'t see anything about cost in the PoC - is
that a topic to be addressed post-hackathon?

We are not optimizing for cost at this earl\... by Mark Hanson

Mark Hanson

7/31 4:30 PM

We are not optimizing for cost at this early stage, if we can get them
interested and meet the performance criteria then cost will be very
important. I suspect until we have SLAB storage it will be hard to be
competitive with things like elasticsearch. However that becomes a
business decision that I am happy for Randy to figure out for
us ![🙂](media/image5.png){width="0.12361111111111112in" height="9.0in"}

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Begin Reference, Question from my team: Wh\... by Mark Hanson

Mark Hanson

7/31 4:32 PM

Steven Lubars7/31/25 3:36 PM

Question from my team: What do we know about machine sizing - will one
of our current t-shirt sizes suffice? Or do we need to work backwards
from performance expectations?

Where is the list of sizes and corresponding hardware listed? I do not
imagine we will have that much data for the hack-a-thon so do not need
any massive storage specified.

August 1

Begin Reference, For any who are interested\... by Benjamin De Boe

Benjamin De Boe

8/1 2:37 AM

Randy Pallotta7/31/25 3:59 PM

For any who are interested, here\'s the write up for the POC 📄 Vector
Search - Proof of Concept Specification Second Draft 2.docx

I left a few comments in the doc, mostly looking for clarification. The
most important thing I think is for us to get more crisp on how we
define accuracy (which usually gets expressed as a chart comparing
recall and latency/throughput, using different parameter settings). We
haven\'t done a lot of that ourselves yet, but it\'s probably how their
team expects us to report if they\'ve looked at other technologies.

Begin Reference, I left a few comments in t\... by Suprateem Banerjee

Suprateem Banerjee

8/1 7:22 AM

Benjamin De Boe8/1/25 2:37 AM

I left a few comments in the doc, mostly looking for clarification. The
most important thing I think is for us to get more crisp on how we
define accuracy (which usually gets expressed as a chart comparing...

I was thinking of benchmarking using a popular BEIR benchmark like
MSMARCO. The main MSMARCO dataset contains 8.8M passages, queries, and
mappings between which queries are answered by which passages. However
they don\'t have embeddings, and embedding 8.8M documents plus queries
might be bit of a challenge. I encountered a dataset by Cohere, where
they already have embedded the MSMARCO passages and queries using the
same mappings. For an apples to apples comparison, we could evaluate
recall@1, recall@5, recall@10, recall@100 for both ElasticSearch and
IRIS.\
\
This benchmark is big enough for evaluating performance, as well as
assessing accuracy. However, this dataset doesn\'t have a lot of
different fields to filter through, so if we want, we might use a
different dataset for evaluating filtered retrieval capabilities.

I\'m not too worried about filtered retrieva\... by Benjamin De Boe

Benjamin De Boe

8/1 8:36 AM

I\'m not too worried about filtered retrieval. That\'s easier to mock up
than generating relevant vectors and queries, and as Mark pointed out at
the top of this thread, we\'ll want to control the selectivity to fully
appreciate performance at different selectivity numbers.

Also, we would be getting data from Epic, though I agree building
experience with established benchmarks doesn\'t hurt. Not sure how much
the differ from / add to what 

Ray

 

Wright

 has been using thus far.

Begin Reference, This is what Ray used for \... by Suprateem Banerjee

Suprateem Banerjee

8/1 8:40 AM

Louis Kabelka7/31/25 3:07 PM

This is what Ray used for his vector search benchmarking - 500k rows:
https://huggingface.co/datasets/Cohere/wikipedia-22-12-simple-embeddings

This dataset, used by Ray, does not have ground truth mappings between
queries and documents, and as such, does not serve as a retrieval
accuracy evaluation dataset.

if you start from the embeddings (no quanti\... by Benjamin De Boe

Benjamin De Boe

8/1 8:41 AM

if you start from the embeddings (no quantization / compression / \...)
and don\'t use the [A]{.underline}NN index but rather calculate all
distances, doesn\'t that give you ground truth?

Ground truth between two copies of a docume\... by Suprateem Banerjee

Suprateem Banerjee

8/1 8:45 AM

Ground truth between two copies of a document, where we expect absolute
similarity? Yes. But that doesn\'t help as a useful retrieval benchmark,
since questions asked by the end user will never be the same body of
text as the document itself. Instead, a benchmark like MSMARCO poses
questions that are answered by documents, and fetches them based on
cosine similarity. Since we have ground truth mappings, we can
accurately evaluate at scale.

Right! by Benjamin De Boe

Benjamin De Boe

8/1 8:46 AM

Right!

Suprateem   Banerjee  your focus on underst\... by Mark Hanson

Mark Hanson

8/1 9:05 AM

Suprateem

 

Banerjee

 your focus on understanding recall rate of IRIS Vector Search compared
to Elasticsearch is a good thing to understand. Getting some comparison
so we are not surprised in the hack-a-thon would be really helpful.

 

If we need to optimize for recall we should start looking at
ColBERT/ColBERTv2, but this would be a fairly significant change in our
vector search so not a quick fix. Ideally at the hack-a-thon we can get
an idea of which metrics Epic cares most about and which ones are not as
important and where recall is in this set.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

for the benchmark I\'ve been inserting 99% o\... by Ray Wright

Ray Wright

8/1 9:09 AM

for the benchmark I\'ve been inserting 99% of the records from the
source dataset into a data table, and 1% into a query table. The
benchmark is driven by embeddings randomly selected from the query table
and run against the data table. We run a TOP n indexed query and a
ground truth query based using the same parameters and compare the
result sets. So\... the queries aren\'t \"questions answered by the
document\" but they\'re not using embeddings that are present in the
data table

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Everyone  I just setup a meeting 10:30-11 t\... by Mark Hanson

Mark Hanson

8/1 9:09 AM

**Everyone** I just setup a meeting 10:30-11 to check in where we are
currently for most (but not all) of the people on this chat. I am
interested in hearing what progress we are making, what questions we
have and what roadblocks we are running into.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Like reactions.

2

i also ran a set of tests where 100% of the\... by Ray Wright

Ray Wright

8/1 9:11 AM

i also ran a set of tests where 100% of the dataset goes into the data
table and 1% also goes into the query table, so that we\'re querying
against embeddings that are present in the data table\... the difference
was minimal

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Begin Reference, Suprateem Banerjee your fo\... by Suprateem Banerjee

Suprateem Banerjee

8/1 9:15 AM

Mark Hanson8/1/25 9:05 AM

Suprateem Banerjee your focus on understanding recall rate of IRIS
Vector Search compared to Elasticsearch is a good thing to understand.
Getting some comparison so we are not surprised in the...

Agreed. However, with ColBERT/V2/ColPali, you are looking at multi
vector retrieval. We don\'t support it natively and like you say, it\'s
a more substantial optimization.\
\
For the time being, using MSMARCO (or similar) for Recall evaluation
doesn\'t need any change to our existing system. Hoping to run some
tests soon to see how we compare.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Like reactions.

**2**

I created a project branch //projects/epich\... by Mark Hanson

Mark Hanson

8/1 9:44 AM

Edited

I created a project branch //projects/epichat which will become the
source of IRIS server logic we will deploy to the cloud for the
hack-a-thon. 

Boya

 

Song

 will be the branch manager, we have a build spec to build
this [[Project-EHAT]{.underline}](https://turbo.iscinternal.com/mbs#/view/Project-EHAT) and
there is an auto-integrate scheduled every day
([[https://turbo.iscinternal.com/pis#/schedule/135]{.underline}](https://turbo.iscinternal.com/pis#/schedule/135)).
I will get a kingtut setup on this shortly.

 

Full list of branches we use as always at
: [[https://usconfluence.iscinternal.com/display/SQL/Data+models+project+branch+status]{.underline}](https://usconfluence.iscinternal.com/display/SQL/Data+models+project+branch+status)

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

3 Like reactions.

3

Begin Reference, Where is the list of sizes\... by Steven Lubars

Steven Lubars

8/1 9:56 AM

Edited

Mark Hanson7/31/25 4:32 PM

Where is the list of sizes and corresponding hardware listed? I do not
imagine we will have that much data for the hack-a-thon so do not need
any massive storage specified.

I was thinking speed more than size.  I don\'t have the t-shirt sizes in
front of me.

Couple of points from talking to Luca:

1\) Storage iops: He suggests we moving from gp3 to io2 (modification to
ICCA CSI) - that way we can start at 20,000 iops, and be able to
increase it if needed (to 64,000 or whatever)

2\) Container size: Roughly how much data are we pre-loading in the
container? Once we get to 12GB or so we hit some kind of AWS limit. If
we don\'t load the data at runtime we might need to stage it on a volume
snapshot or in S3 and mount or load at deploy time.

On data size, this is a good question for  \... by Mark Hanson

Mark Hanson

8/1 10:05 AM

Edited

On data size, this is a good question for 

Jose

 

Ruperez

 to add to his list to get from Epic. In initial meeting with Epic it
did not sound like they wanted to push a lot of data for the hat so
below 1GB. Also due to the smallish expected data amount (for the POC)
we can assume the data will be all in global buffers so IOPS should not
matter much. Having a decent number of CPUs for parallel
dot-product/cosine and HNSW search work would be helpful however, so I
expect us to be CPU compute bound.

Luca suggesting: image by Steven Lubars

Steven Lubars

8/1 10:14 AM

Luca suggesting:

Message by Zelong Wang, has an attachment.

Zelong Wang

8/1 10:15 AM

**Open_source_Vector_search_engine_Benchmark_studies 1.pdf**

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Begin Reference, Luca suggesting: 📷, Ste\... by Mark Hanson

Mark Hanson

8/1 10:22 AM

Steven Lubars8/1/25 10:14 AM

Luca suggesting: 📷

Looks great, thanks Steve.

Zelong   Wang  are you making a recommendat\... by Mark Hanson

Mark Hanson

8/1 10:24 AM

Zelong

 

Wang

 are you making a recommendation with the pdf or is this just for
information?

Just for information --- we're still in the p\... by Zelong Wang

Zelong Wang

8/1 10:26 AM

Just for information --- we're still in the process of researching the
environment setup for benchmarking

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

We don\'t want Epic having to use their own \... by Steven Lubars

Steven Lubars

8/1 10:31 AM

We don\'t want Epic having to use their own credit card, and we don\'t
want to allow \"free trials\" (especially if we lift some restrictions
on %SQL_Admin), so we\'ll probably modify the portal for their feature
environment to only allow registration by \@intersystems.com and
\@epic.com email addresses.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Begin Reference, I created a project branch\... by Benjamin De Boe

Benjamin De Boe

8/1 11:01 AM

Mark Hanson8/1/25 9:44 AM

I created a project branch //projects/epichat which will become the
source of IRIS server logic we will deploy to the cloud for the
hack-a-thon. Boya Song will be the branch manager, we have a build spec
to build this Project-EHAT and there is an auto-integrate scheduled
every day (https://turbo.is...

what are we auto-integrating from? For the sake of stability maybe we
don\'t want too much bleeding-edge work seeping in from //projects/sql
and just pick what we need.

It is integrating from //iris/latest and we\... by Mark Hanson

Mark Hanson

8/1 11:02 AM

It is integrating from //iris/latest and we will pick and choose any
specific vector search logic we may want in here.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

I kicked off a build from our new branch : \... by Mark Hanson

Mark Hanson

8/1 11:04 AM

I kicked off a build from our new branch : 2025.3.0EHAT.101.0 so we can
see if this builds and has the right build config settings.

High priority / blocking question:  Any pre\... by Steven Lubars

Steven Lubars

8/1 11:06 AM

High priority / blocking question:  Any preference on what we call the
portal?  icca-epic?  icca-sql?  icca-vector?  (has to be prefixed with
icca-)

Where does this name gets used/viewed? Init\... by Mark Hanson

Mark Hanson

8/1 11:08 AM

Edited

Where does this name gets used/viewed? Initial suggestion icca-epichat
for Epic hack-a-thon as it is specific to this event rather than some
general longer lived epic portal.

(Rick is ready to create the portal now bef\... by Steven Lubars

Steven Lubars

8/1 11:09 AM

(Rick is ready to create the portal now before he goes on PTO)

Name shows up in URL of the portal where they authenticate, select the
service they want, and click \"Deploy\"

Let\'s go with icca-epichat then, thanks Ste\... by Mark Hanson

Mark Hanson

8/1 11:12 AM

Let\'s go with icca-epichat then, thanks Steve.

URL will be something like: Link https://po\... by Steven Lubars

Steven Lubars

8/1 11:14 AM

URL will be something like:

[[https://portal.icca-epichat.inp.isccloud.io]{.underline}](https://portal.icca-epichat.inp.isccloud.io/) 

 

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Like reactions.

2

Another important question: are we presenti\... by Steven Lubars

Steven Lubars

8/1 3:41 PM

Another important question: are we presenting this as SQLaaS, or as a
new offering?  And if the latter, what is the right name for it (e.g.
does it have "vector" in its name)?

I would think somethng with \"Vector\" in its\... by Jose Ruperez

Jose Ruperez

8/1 3:49 PM

I would think somethng with \"Vector\" in its name

This would be a question for PM i.e Benjam\... by Mark Hanson

Mark Hanson

8/1 3:49 PM

This would be a question for PM i.e 

Benjamin

 

De

 

Boe

If this is blocking you getting something s\... by Mark Hanson

Mark Hanson

8/1 3:51 PM

Edited

If this is blocking you getting something setup then use whatever we
have for IRIS SQL in the cloud already and we can change this later if
wanted

Sure. this is not a final prodcut this is j\... by Jose Ruperez

Jose Ruperez

8/1 3:51 PM

Sure. this is not a final prodcut this is just a PoC

If the answer to \"if things go really well,\... by Steven Lubars

Steven Lubars

8/1 4:26 PM

If the answer to \"if things go really well, would this become an
offering distinct from SQLaaS\" is \"yes\", then we should go with a
distinct name now (even if we change it later).  This is not a blocker
because its external name in the Portal is easy to change (internally
we\'ll call it \"vector\" for now).  Suggestions for the external name
welcome.

The service we are aiming to stand up is go\... by Mark Hanson

Mark Hanson

8/1 5:45 PM

The service we are aiming to stand up is going to be IRIS cloud SQL with
a few enhancements around improved vector search logic which would be
going into the product anyway and perhaps an improved SQL REST interface
which we would want in IRIS cloud SQL as well. So at this point from a
technical perspective it is the same product/offering, however
sales/marketing/pm are free to draw whatever lines they like here as
this is a business decision not a technical one.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

6 Like reactions.

6

August 3

Indeed, we already considered and decided a\... by Benjamin De Boe

Benjamin De Boe

8/3 8:21 AM

Indeed, we already considered and decided against releasing a separate
pure vector DB service last year. At least until there\'d emerge a more
crisp API that is focused squarely on vectors and possibly an associated
nuance on the storage backing the service, this fits very well with
Cloud SQL and our positioning of Vector Search as a fully embedded
capability with the flexibility full SQL buys you.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Like reactions.

2

August 4

Dave   VanDeGriek  is looking into building\... by Mark Hanson

Mark Hanson

8/4 10:24 AM

Dave

 

VanDeGriek

 is looking into building a PostgREST interface to SQL so that we have a
REST API that both performs better and is cleaner for the hack-a-thon.
The idea is to start with the simple stuff to begin with (along with
vector search specifics like VECTOR_COSINE) and then build it out as
needed. If Dave has questions about writing %CSP.REST.cls interfaces for
IRIS has anyone on this thread done any REST specific work and so may be
able to help?

For now lets get everything working against\... by Mark Hanson

Mark Hanson

8/4 10:27 AM

For now lets get everything working against the existing REST interface
and we can see about switching to this other interface if Dave\'s work
goes well.

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

2 Like reactions.

2

With Jose out this week who is handling com\... by Mark Hanson

Mark Hanson

8/4 10:38 AM

With Jose out this week who is handling communication with Epic?

Begin Reference, With Jose out this week wh\... by Nicholai Mitchko

Nicholai Mitchko

8/4 10:52 AM

Edited

Mark Hanson8/4/25 10:38 AM

With Jose out this week who is handling communication with Epic?

We will sort that out in
sales ![🙂](media/image5.png){width="0.12361111111111112in"
height="9.0in"}

![❤️](media/image4.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Heart reaction.

Mark   Hanson   Steven   Lubars  Where can \... by Nicholai Mitchko

Nicholai Mitchko

8/4 10:54 AM

Mark

 

Hanson

 

Steven

 

Lubars

 Where can we get access to a Cloud SQL and REST endpoints for it? I see
cloud SQL in my cloud portal but want to make sure we\'re working on the
closest to latest versions

Moreover, how can we get the bearer token w\... by Nicholai Mitchko

Nicholai Mitchko

8/4 11:06 AM

Moreover, how can we get the bearer token without logging into my
portal? For example, I copied the below request from the console
inspector in chrome, but it includes the bearer token.

The doc link on the cloud portal leads to a\... by Nicholai Mitchko

Nicholai Mitchko

8/4 11:07 AM

The doc link on the cloud portal leads to a dead link

 

Steven   Lubars  can you answer these quest\... by Mark Hanson

Mark Hanson

8/4 11:08 AM

Steven

 

Lubars

 can you answer these questions or add someone from your team who can
address these details?

Nicholai   Mitchko  the version in the port\... by Steven Lubars

Steven Lubars

8/4 11:09 AM

Nicholai

 

Mitchko

 the version in the portal is latest - getting info on REST endpoints
now

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Just to confirm, which portal are you looki\... by Steven Lubars

Steven Lubars

8/4 11:14 AM

Just to confirm, which portal are you looking at?

Token is the Authorization header that you \... by Steven Lubars

Steven Lubars

8/4 11:15 AM

Token is the Authorization header that you can grab from browser
devtools - someone has a postman that grabs it, looking now

We\'re not sure why the doc link is bad - th\... by Steven Lubars

Steven Lubars

8/4 11:17 AM

We\'re not sure why the doc link is bad - the top level page works:

[[https://docs.intersystems.com/components/csp/docbook/DocBook.UI.Page.cls]{.underline}](https://docs.intersystems.com/components/csp/docbook/DocBook.UI.Page.cls)

but nothing underneath it for ADRIVE

You can try the following: curl \--location \... by Steven Lubars

Steven Lubars

8/4 11:22 AM

You can try the following:

curl
\--location \'[[https://cognito-idp.us-east-2.amazonaws.com/\']{.underline}](https://cognito-idp.us-east-2.amazonaws.com/%27) \\

\--header \'X-Amz-Target:
AWSCognitoIdentityProviderService.InitiateAuth\' \\

\--header \'Content-Type: application/x-amz-json-1.1\' \\

\--header \'Authorization: ••••••\' \\

\--data \'{

      \"AuthParameters\": {

        \"USERNAME\": \"\<USERNAME\>\",

        \"PASSWORD\": \"\<PASSWORD\>\"

      },

      \"AuthFlow\": \"USER_PASSWORD_AUTH\",

      \"ClientId\": \"1cuuc3fhp8u4b1q92v5gfmcvms\"

    }

ClientId changes based on the portal (above is for epichat, for which
we\'re still standing up the back end)

For the doc link, I would reach out to Dere\... by Steven Lubars

Steven Lubars

8/4 11:25 AM

For the doc link, I would reach out to Derek (or maybe Peter Z or Mark
Lo).  Changing ADRIVE to GDRIVE seems to provide better results, but the
REST API isn\'t documented

It\'s documented in our swagger but we don\'t\... by Steven Lubars

Steven Lubars

8/4 11:34 AM

It\'s documented in our swagger but we don\'t have customer-facing
documentation on the REST API - as we provide information and you start
using it, will you be able to turn it into something suitable for
consumption by Epic?

Swagger is here: Link https://gitlab.iscint\... by Steven Lubars

Steven Lubars

8/4 11:44 AM

Swagger is here:

[[https://gitlab.iscinternal.com/cs/icca/-/blob/develop/swagger/swagger.yaml]{.underline}](https://gitlab.iscinternal.com/cs/icca/-/blob/develop/swagger/swagger.yaml)

 

e.g. POST /sql/query: {   \"connection\": {\... by Steven Lubars

Steven Lubars

8/4 11:45 AM

e.g. POST /sql/query:

{\
  \"connection\": {\
    \"username\": \"string\",\
    \"password\": \"string\",\
    \"port\": \"string\",\
    \"namespace\": \"string\",\
    \"host\": \"string\",\
    \"networkTimeout\": \"string\"\
  },\
  \"deploymentId\": \"string\",\
  \"sql\": {\
    \"query\": \"string\",\
    \"maxRows\": \"string\",\
    \"maxLength\": \"string\"\
  }\
}

200

{\
  \"result set\": \[\
    {\
      \"name\": \[\
        \"ID\",\
        \"name\",\
        \"tel\",\
        \"personId\"\
      \],\
      \"type\": \[\
        \"BIGINT\",\
        \"VARCHAR\",\
        \"INTEGER\",\
        \"INTEGER\"\
      \],\
      \"data\": \[\
        \[\
          \"1\",\
          \"Robert\",\
          \"4872\",\
          \"1111\"\
        \],\
        \[\
          \"2\",\
          \"Jerome\",\
          \"91071\",\
          \"2222\"\
        \],\
        \[\
          \"3\",\
          \"Philip\",\
          \"5877\",\
          \"3333\"\
        \],\
        \[\
          \"4\",\
          \"William\",\
          \"71789\",\
          \"4444\"\
        \]\
      \]\
    }\
  \],\
  \"error\": \"\",\
  \"rows updated\": \"10\"\
}

 

 

Got this when trying to find your link by Nicholai Mitchko

Nicholai Mitchko

8/4 12:10 PM

Got this when trying to find your link

image by Nicholai Mitchko

Nicholai Mitchko

8/4 12:10 PM

Just sent you an invite to the project by Steven Lubars

Steven Lubars

8/4 12:13 PM

Just sent you an invite to the project

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

Begin Reference, It\'s documented in our swa\... by Nicholai Mitchko

Nicholai Mitchko

8/4 12:13 PM

Steven Lubars8/4/25 11:34 AM

It\'s documented in our swagger but we don\'t have customer-facing
documentation on the REST API - as we provide information and you start
using it, will you be able to turn it into something suitable for
consumption by Epic?

We\'d create a write-up for the poc, but certainly would be nice to have
this as part of the service

Do we have rest end points for data retriev\... by Nicholai Mitchko

Nicholai Mitchko

8/4 12:19 PM

Do we have rest end points for data retrieval? I see /sql/query but that
would require the user to create SQL each time and seems like an
injection risk

Either that, or perhaps is there a timeline\... by Nicholai Mitchko

Nicholai Mitchko

8/4 12:19 PM

Either that, or perhaps is there a timeline for the pgRest
implementation?

For comparison, elasticsearch uses this api\... by Nicholai Mitchko

Nicholai Mitchko

8/4 12:20 PM

For comparison, elasticsearch uses this api:

 

\_search provides a vector search against a\... by Nicholai Mitchko

Nicholai Mitchko

8/4 12:21 PM

\_search provides a vector search against an index

Just whatever is allowed in a SQL session by Steven Lubars

Steven Lubars

8/4 12:22 PM

Just whatever is allowed in a SQL session

![👍](media/image2.png){width="0.2777777777777778in"
height="0.2777777777777778in"}

1 Like reaction.

If you can do it in SQL, you can do it in /\... by Steven Lubars

Steven Lubars

8/4 12:23 PM

If you can do it in SQL, you can do it in /sql/query - is this something
different?

SQL security handles the injection risk as \... by Mark Hanson

Mark Hanson

8/4 12:23 PM

SQL security handles the injection risk as only users allowed to do the
specific SQL operation can run that command (same via ODBC/JDBC).

FYI: DaveV is an expert on SQL security by Mark Hanson

Mark Hanson

8/4 12:23 PM

FYI: DaveV is an expert on SQL security

Yes, DaveV was instrumental in creation of \... by Steven Lubars

Steven Lubars

8/4 12:24 PM

Yes, DaveV was instrumental in creation of the roles used by ICCA

I mean having the user send the raw query d\... by Nicholai Mitchko

Nicholai Mitchko

8/4 12:26 PM

I mean having the user send the raw query down to the instance is
screaming for someone to hijack the token and write their own SQL

Anyways, we can worry about that later by Nicholai Mitchko

Nicholai Mitchko

8/4 12:26 PM

Anyways, we can worry about that later

There is no difference between Elasticsearc\... by Mark Hanson

Mark Hanson

8/4 12:28 PM

There is no difference between Elasticsearch and IRIS model via SQL in
terms of risk as long as SQL security is setup correctly. So you allow a
user query access to a table and now they can run SQL queries, someone
that can grab this token can also run queries against this table, but in
the Elasticsearch model with the equivalent token they can run new
elasticsearch queries too with the access token.

Other things like user defined SQL function\... by Mark Hanson

Mark Hanson

8/4 12:29 PM

Other things like user defined SQL functions are disabled in the cloud
because of this risk

Dave VanDeGriek here are the paradigms I am using in SQL that would be
worth having in REST

 

CREATE TABLE IF NOT EXISTS  Sample.Embeddings (

    ID INTEGER IDENTITY PRIMARY KEY,

    Embedding VECTOR(FLOAT, 768)

)

INSERT %NOLOCK {SQLARGS} INTO Sample.Embeddings (Embedding)

VALUES (TO_VECTOR(?, FLOAT))

SELECT TOP 5 ID

FROM Sample.Embeddings

ORDER BY

    VECTOR_DOT_PRODUCT(Embedding,TO_VECTOR(?, FLOAT))

    DESC

 

 

 

We will punt on the \'create table\' syntax for now but will look into
the insert/select cases.

 

You should drop the \'%NOLOCK\' on the INSERT as this often causes
strange errors (Dave has some war stories around this!)

 That looks fine to me, what % of your hardware memory are you
allocating to global buffers with this?

 

I have 32GB on this instance and 20GB globuf

 

The entire table should fit into memory here

 

quick update on the benchmarking, we an an AWS 16CPU machine that we are
testing against

 

I re-ran ingestion with this merge above, and we\'re maxing the CPU, but
we still hit a limit of the same number of rows

 

![image](media/image6.jpeg){width="5.555555555555555in"
height="3.3097222222222222in"}

 

I then ran on my own laptop and get similar results, I suspect the
TO_VECTOR(?, is the bottle neck)

 

Increasing lock threshold to 10000 makes the 2000x/s number event out
for larger batch sizes (1024 x 8 clients) has no issues

 

we will retest once the \$vop ( from binary ) is ready

 

working on select test now

 

FYI: Rob has just checked in logic to improve the conversion from binary
form to \$vector form and Dave just tested it as around 80x faster than
before and is also working on integrating this into RESTQL interface 

 

Hi guys, here is my throughput analysis for search

 

this is in select top 10 VDP per second

 

Same benchmark as the backend code for the demo

 

(ignore this chart in this previous message)

 

ROWS = the number of concurrent queries made in the test, clients is the
number of concurrent clients

 ok, my change only optimized the case with the TO_VECTOR input in JSON
Array string format:
 TO_VECTOR(\'\[-0.027910689339473438,0.016369994270021334,\...,0.020773508175814907\]\',
FLOAT) \...

 

Let me update it to include support for a comma-delimited string.

 

we can just put brackets in there

 

The real fix is to change the SQL preparser to allow literal
substitution for the TO_VECTOR(\...) function if TO_VECTOR(\...) is
within an ORDER BY clause, but that is a bigger change.

 

See if that makes a difference with the number of cached queries.

 

Mark Hanson added Yiwen Huang to the chat and shared all chat history.

 

Added Yiwen Huang to the chat as she will work on improving the SQL
pre-parser to allow literal substitution in TO_VECTOR
([[DP-444330]{.underline}](https://usjira.iscinternal.com/browse/DP-444330))

 

So I see the TO_VECTOR sql statment has a ? before prepare, but still
results in a net-new cached query on .127

 

What is .127?  Are you not seeing the cached query is now like:  

 

SELECT %NOLOCK TOP ? ID AS IDENTIFIER FROM QUERYSUITE1 .
UNINDEXEDEMBEDDINGS ORDER BY VECTOR_DOT_PRODUCT ( EMBEDDING , TO_VECTOR
( ? , FLOAT ) ) DESC  /\*#OPTIONS {\"IsolationLevel\":0} \*/ 
/\*#OPTIONS {\"DynamicSQLTypeList\":10} \*/

 

Also, you don\'t really need %NOLOCK for SELECT.  It doesn\'t hurt, but
doesn\'t mean anything unless the process is in READ_COMITTED mode.

 

FYI: It looks like our call with Epic about scheduling the hackathon was
pushed back to Tuesday 16th at 10am

 

Everyone Update from meeting with Epic:

 

Nicholai did a really nice presentation of what we have done including
RESTQL/ACORN-1 and a demo of vector search in a MyChart like app using
this REST interface that showed the end to end vector search idea
working. While Epic expressed interest in where we are going here they
are currently heads down adding AI capabilities to their product and do
not have any time to look into alternative vector search engines at the
moment. This means there are no immediate plans for a hackathon with
them on vector search, but we agreed to talk more in the first quarter
2026.

 

This project between development and sales has been highly successful.
It proved we can stand up a vector search service in the cloud and then
rapidly iterate on what this service provides by adding a high
performance REST interface and a major new algorithm with ACORN-1. Sales
engineering provided invaluable testing and benchmarking of these
interfaces that allowed development to fix a bunch of performance hot
spots and bad behavior and get this service into a state where we can
have confidence that the hackathon would have been successful.

 

Development has a little more work to do in order to make ACORN-1 a full
product feature in figuring out a cost model for this so we can turn it
on automatically. I will also discuss with Benjamin if IRIS SQL needs a
REST interface baked into the product and if so what that interface
would look like.

 

Thank you everyone for all your hard work on this project. I am very
much looking forward to future beneficial collaborations between sales
and development. 

 Thank you all for the amazing engagement and collaboration. I think
this exercise brought in value in multiple dimensions both tangible and
intangible. I think earning the right for the next conversation is very
important. Would love to do some more conversations and digging w epic
on the challenges that epic thinks we may be able to help. 

Until we engage with Epic again in Q1 2026, Steven Lubars and team could
add Azure as an option? That was their first question, right?

 

Yup Azure was their first question and would be required for Epic

 

It\'s on the PM roadmap for 2026 (behind dedicated infrastructure, HA,
and multi-region DR Async).

 

If we were going to change priorities or schedule, Epic would be a
compelling reason - but has to get worked out at a higher level.

 
