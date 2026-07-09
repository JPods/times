# MeshMobility Training Videos — Scripts

## Video List (recommended order)

| # | Title | Length | Audience | Purpose |
|---|-------|--------|----------|---------|
| 1 | **60-Second CityTool** | 1 min | Capital sources, city officials | Hook — see your city's numbers |
| 2 | **Your First Network in 5 Minutes** | 5 min | Designers, community teams | Get started — search, overlay, draft, wild guess |
| 3 | **Reading the Data** | 3 min | Designers | What the overlays mean and how to use them |
| 4 | **Designing with Noelle** | 4 min | Designers | Draft, Apply, Wild Guess, Refine workflow |
| 5 | **Manual Design — Keys 1-9** | 3 min | Designers | Place, connect, move, select, delete, walk radius |
| 6 | **Running a Simulation** | 3 min | Designers, presenters | Run, replay, isochrone, read results |
| 7 | **The Report — Capital Pitch** | 2 min | Capital sources, presenters | Generate and walk through the report |
| 8 | **Why JPods — 60 Seconds** | 1 min | Everyone | The elevator pitch with numbers |

---

## Video 1: 60-Second CityTool
**Length:** 60 seconds
**Audience:** Capital sources, city officials, anyone curious
**Goal:** Type a city, see the savings. Spark curiosity.

### Script

[Screen: CityTool open, empty]

"Pick any US city. I'll type Tulsa, Oklahoma."

[Type: Tulsa, OK — hit Enter]

"Census data loads automatically. Population 412,000. 170,000 households. 
Walk Score 30 — car dependent."

[Pause on the four big numbers at top]

"$3.78 billion to build. $1.61 billion per year in savings. 7-year payback.
840,000 tons of CO2 eliminated per year."

[Scroll to savings breakdown]

"Where does the savings come from? Vehicle ownership — 173,000 fewer cars 
at $9,282 each. Fuel savings. Road maintenance reduction. 
And $5 billion in capital unlocked from eliminated vehicles."

[Scroll to land use]

"The fiscal argument to cities: convert 60% car-centric land to walkable 
commercial and recreational. $322 million per year in fiscal improvement."

"Try your city. The link is in the description."

[End card: rtb.webclerk.com/citytool]

---

## Video 2: Your First Network in 5 Minutes
**Length:** 5 minutes
**Audience:** New designers, community teams
**Goal:** From zero to complete network with simulation

### Script

[Screen: MeshMobility open, empty map]

"Let's design a JPods network for Richardson, Texas in five minutes."

**Step 1 — Find your city (0:00-0:30)**

[Click Find City]

"Click Find City. Type Richardson, TX. Go."

[Map flies to Richardson]

"The orange dashed line is the city boundary."

**Step 2 — Fetch the data (0:30-1:00)**

[Click Overlays]

"Click Overlays, then Fetch Data. This pulls traffic counts, crash locations, 
and census data — population, property values, jobs — all from free 
government sources."

[Wait for fetch to complete. Toggle on Fatal Crashes and Traffic]

"Red circles are fatal crash locations. Sized circles are traffic volume. 
This is where people are dying and where vehicles concentrate."

**Step 3 — Let Noelle draft (1:00-2:00)**

[Click Tools, then Draft]

"Click Tools, then Draft. Noelle reads the crash and traffic data and 
proposes station locations. Purple dots — each one is a proposed station 
placed where the data says people need safe transportation."

[Click Apply]

"Click Apply to place them as real stations on the network."

**Step 4 — Wild Guess (2:00-2:30)**

[Click Wild Guess]

"Click Wild Guess. Noelle adds traffic circles between station pairs and 
connects everything. One click — complete network."

[Pause on the mesh]

"That's a connected mesh network. Multiple paths between every pair of 
stations. No single point of failure."

**Step 5 — Simulate (2:30-3:30)**

[Click Run in the Simulate section]

"Click Run. The simulation dispatches pods from every station to every 
other station. Blue pods on the guideways — watch them move."

[Wait for simulation to complete]

"Results: average trip time, throughput, congestion. 
Click Isochrone — click any point on the map — see how far you can 
travel in 5, 10, 20, 30 minutes including walking to and from stations."

**Step 6 — Save and Report (3:30-4:30)**

[Click Save]

"Save your network as a .jpd file. All the overlay data is embedded — 
one file, everything inside."

[Click Report]

"Click Report for a printable summary: stations, circles, guideway miles, 
build cost, capacity tables, and the evidence base. 
This is your capital presentation."

**Step 7 — CityTool (4:30-5:00)**

[Click CityTool button]

"Click CityTool to see the full economic analysis for your city. 
Savings, payback period, CO2 reduction, fiscal impact."

"Five minutes. You just designed a transit network. Save it, share it, 
or start refining."

[End card: rtb.webclerk.com]

---

## Video 3: Reading the Data
**Length:** 3 minutes
**Audience:** Designers learning to use overlays
**Goal:** Understand what each overlay shows and why it matters

### Script

[Screen: MeshMobility with Asheville loaded]

"Six data layers. Each one tells you something different about where 
JPods stations belong."

[Toggle Traffic AADT]

"**Traffic** — annual average daily traffic from state DOT. 
Circle size equals vehicle volume. These are the corridors carrying 
the most cars. JPods reduces congestion on these roads."

[Toggle Fatal Crashes]

"**Fatal Crashes** — NHTSA data, four years. Blue circles. 
These are where the road system kills people. Every dot is a death 
that JPods eliminates by removing vehicle-miles."

[Toggle Crash Density]

"**Crash Density** — fatal crashes aggregated to a grid. 
This is Noelle's primary placement signal. Local arterials are 
9x more dangerous per unit of traffic than interstates. 
Highways are boundaries, not corridors."

[Toggle Population Density]

"**Population** — census tracts. Purple equals dense. 
Where people live. Stations near dense tracts mean high ridership."

[Toggle Jobs]

"**Jobs** — employed civilians by tract. Blue equals concentrated. 
Where people work. The gap between where people live and where they 
work IS the commute — and the JPods revenue corridor."

[Toggle Property Values]

"**Property Values** — median home value by tract. Green equals higher. 
The tax base argument: JPods stations increase nearby property values 
10-20%. Convert parking to walkable land, the city's tax revenue grows."

[Press 9 — walk radius circle]

"Press 9 for the walk radius. This orange circle is three-quarters of 
a mile — a 15-minute walk. If every point in your city is inside one 
of these circles, every resident can walk to a station."

[End card: data sources listed]

---

## Video 4: Designing with Noelle
**Length:** 4 minutes
**Audience:** Designers using the Noelle workflow
**Goal:** Draft → Apply → Wild Guess → Refine → Report

### Script

[Screen: MeshMobility, city loaded with overlays]

"Noelle is the network design agent. She reads government data and 
proposes stations. You add local knowledge."

**Draft (0:00-1:00)**

[Click Draft]

"Draft shows Noelle's proposal as a purple overlay. She places stations 
where crash data and traffic data intersect. Stations only — 
circles are your job, because only you know where corridors cross."

[Hover over a few draft stations — show tooltips]

"Each proposal shows crash count and traffic volume. 
Higher numbers mean stronger signal."

**Apply (1:00-1:30)**

[Click Apply]

"Apply places Noelle's stations as real structures on the network. 
The draft layer disappears — they're real now."

**Wild Guess (1:30-2:00)**

[Click Wild Guess]

"Wild Guess adds traffic circles between station pairs and connects 
everything. It's rough — that's why it's called Wild Guess. 
But it gives you a complete network to start refining."

**Refine (2:00-3:00)**

"Now you refine. Move stations to buildable sites — Alt-drag. 
Delete structures that don't make sense — Shift-drag to select, Delete key. 
Add stations where you know the traffic — keys 1-4."

[Show moving a station, deleting one, adding one]

"Press 9 for the walk radius. Check coverage — every gap is someone 
who can't walk to a station."

**Local Knowledge (3:00-3:30)**

[Click Local Knowledge]

"Noelle asks questions she can't answer from data. Bike trails, 
university campuses, hospitals, venues. Your answers improve 
her next draft."

**Report (3:30-4:00)**

[Click Report]

"Report generates a printable summary. Stations, miles, build cost, 
capacity, the evidence base. Print it or share the link."

[End card]

---

## Video 5: Manual Design — Keys 1-9
**Length:** 3 minutes
**Audience:** Designers who want full control
**Goal:** All keyboard shortcuts demonstrated

### Script

[Screen: MeshMobility, city loaded]

"Nine keys. Everything you need."

"**1 through 4** — stations. 1 is north-south. 2 east-west. 
3 northwest-southeast. 4 northeast-southwest. 
Click the map to place. Esc to cancel."

[Demo each — place 4 stations quickly]

"**5 and 6** — traffic circles. 5 is standard, arms north-east-south-west. 
6 is rotated 45 degrees. Place where corridors cross."

[Demo — place 2 circles]

"Click a CP on one structure, then a CP on another — connected. 
Two guideways, both directions."

[Demo connection]

"**7 and 8** — zoom in, zoom out."

"**9** — walk radius. Three-quarter mile circle follows your cursor. 
15-minute walk. Check your station spacing."

[Demo — toggle walk radius, move cursor between stations]

"**Alt-drag** any CP to move a structure. 
**Shift-drag** to select a group. **Delete** to remove. 
**Ctrl-Z** to undo — up to 20 levels."

[Demo each]

"**Ctrl-click** a guideway to remove the pair. 
**Shift-click** a CP to disconnect."

"That's it. Nine keys plus mouse. Design a network."

[End card: key reference shown]

---

## Video 6: Running a Simulation
**Length:** 3 minutes
**Audience:** Designers, presenters
**Goal:** Run simulation, read results, use isochrone

### Script

[Screen: MeshMobility with connected network]

"You've built a network. Now test it."

[Click Run]

"Run dispatches a pod from every station to every other station. 
Watch the blue pods — they show traffic flow and congestion points."

[Wait for completion]

"Results panel shows throughput, average trip time, longest trip. 
The station-by-station grid shows travel time between every pair."

[Click Isochrone]

"Click Isochrone, then click any point on the map. 
Green = 5 minutes total journey. Blue = 10. Yellow = 20. Red = 30. 
That includes walking to the station, riding, and walking to your destination."

[Click a point — show the isochrone zones]

"Gray stations are unreachable — usually means an open CP. 
Go back to edit mode, connect the gap, run again."

[Click Replay]

"Replay shows the animation. Pod colors: white is parked, 
orange is in the station siding, green is cruising. 
Watch where pods bunch up — that's where you need more capacity."

[End card]

---

## Video 7: The Report — Capital Pitch
**Length:** 2 minutes
**Audience:** Capital sources, presenters
**Goal:** Walk through the report as a pitch document

### Script

[Screen: Report page open]

"This is your capital document. Generated automatically from your 
network design."

[Point to metrics at top]

"Top line: stations, circles, guideway miles, build cost. 
These are the numbers an investor needs first."

[Scroll to BOM]

"Bill of materials: guideway at $20 million per mile, stations, 
circles, vehicles. Total estimated build cost."

[Scroll to capacity]

"Guideway capacity: 14,400 pods per hour per direction at quarter-second 
headway. But the real constraint is station slots — the station is 
a parallel processor. Add slots where demand concentrates."

[Scroll to parking]

"The hook: your city spends as much on free parking as on educating 
your children. JPods eliminates parking demand and converts that land 
to productive tax base."

[Scroll to streetcar comparison]

"This isn't new technology. In 1916 every American city over 10,000 
had privately funded streetcar networks. Federal highway policy 
destroyed them. JPods restores the model — grade-separated, 
solar-powered, privately funded."

[Scroll to studies]

"The evidence: Congressional study 1975, NJ Legislature, Boeing lean 
manufacturing analysis. And the 5x5 Standard — the regulatory path."

"Print this. Hand it to your city council. Hand it to your investor. 
The numbers speak."

[End card: rtb.webclerk.com/citytool]

---

## Video 8: Why JPods — 60 Seconds
**Length:** 60 seconds
**Audience:** Everyone — the elevator pitch
**Goal:** One minute, the whole story

### Script

[Screen: split — traffic jam on left, JPods rendering on right]

"Americans spend $2.76 trillion a year on traffic. 
Your car costs $9,282 a year and sits parked 95% of the time. 
85% of that money leaves your local economy."

"In 1916, every American city had privately funded streetcar networks. 
Federal highway policy destroyed them and locked in the 25 mpg 
efficiency of the Model T — for a century."

"JPods restores what worked. Solar-powered pods on overhead guideways. 
13 times more efficient than cars. 3,000 times safer. 
$0.03 per passenger mile. No oil. No traffic. No parking lots."

"Tulsa: $3.78 billion to build. $1.61 billion per year in savings. 
7-year payback. 840,000 tons of CO2 eliminated."

"Oil depletes with use. Ingenuity increases with use. 
JPods is a 10x paradigm shift."

"Design your city's network right now — the tools are free and open source."

[End card: rtb.webclerk.com — CityTool — 5x5FreeMarket.com]
