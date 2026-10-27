## What I Built

I built Prompt Lab with Claude Code. It's a single-file web app in plain HTML, CSS, and JavaScript that sends prompts to Claude through the Anthropic API. I paste my API key in each session, and the app keeps it in memory only and never saves it to a file. The app has an optional system prompt, a labeled conversation log, a New Conversation button, and an Export button that downloads the chat as a Markdown file with the model name on the first line and each message under its own heading.

I used Prompt Lab for four tasks for Wildframe Coffee Roasters, a fictional specialty roaster. Each task used a system prompt describing the company and its warm, plainspoken, slightly irreverent brand voice. Task 1 used a zero-shot prompt: with no examples, only instructions and a required format, Claude wrote six subscriber perk ideas, each one sentence of 25 words or fewer. Task 2 used a one-shot prompt: the system prompt included a single example bean card, and Claude followed that house format to write cards for three new coffees. Task 3 used a few-shot prompt: the system prompt included four past customer comments with Wildframe's replies, and Claude matched their tone in three new replies of 40 words or fewer. Task 4 used a chain-of-thought approach: Claude worked through visitors, buy rates, sales, and rent for three pop-up locations step by step against a $5,000 budget before ending with a one-line recommendation. All four runs used `claude-sonnet-5-5`, and their exports are in this folder as `prompt-lab-Task-01` through `prompt-lab-Task-04`.

## Why This Approach

Task 1 - Technique: zero-shot

Brainstorming perk ideas is an open-ended creative task, and an example perk would likely have steered Claude toward copies of that one idea instead of six different ones. The task's real requirements were structural (exactly six numbered ideas, one sentence each, 25 words or fewer), and those are easy to state as plain instructions without showing an example. The system prompt already supplied the brand voice and customer profile, so Claude had the context it needed without any samples.

Task 2 - Technique: one-shot

Bean cards follow a fixed house template with set labels in a set order (Roast, Tastes like, Brew it, Real talk), and the easiest way to pin down an exact layout is to show one finished card. A single example was enough because every card has the same structure; only the coffee details change. The example's "Real talk" line also showed the kind of short, joking tone that line should have, which would be hard to describe in instructions alone.

Task 3 - Technique: few-shot

Brand voice is hard to describe but easy to recognize, so several examples teach it better than an instruction like "be warm and a little irreverent." The four past replies covered different situations (a skeptical question, a complaint, praise, and a how-to question), which showed Claude how the voice adapts to each kind of comment rather than giving it one reply to imitate. That variety mattered because the three new comments were also different: a late delivery, a product question, and a thank-you.

Task 4 - Technique: chain-of-thought

Choosing a pop-up location takes several steps of arithmetic: visitors times buy rate times average sale, minus rent, plus a check of each location's four-week rent against the $5,000 budget. Working through those steps in order makes math errors less likely and lets a reader check each number before trusting the answer. The data also includes a trap that a quick answer could fall into: Union Station has by far the most visitors but loses money every week and goes over the budget, and only the step-by-step comparison shows that clearly.

## Example Run

Model: claude-sonnet-5-5

### System

THE COMPANY: Wildframe Coffee Roasters is a fictional specialty coffee roaster that sells beans online and through a monthly subscription. Brand voice: warm, plainspoken, and a little irreverent, with no corporate jargon. Customers: environmentally conscious urban professionals.

Pop-up location data (weekly figures from comparable past events):

Riverside Farmers Market: 9,000 visitors per week; 2% of visitors buy; average sale $14 (mostly whole-bean bags); rent $900 per week.
Union Station concourse: 30,000 visitors per week; 0.5% of visitors buy; average sale $6 (mostly single cups); rent $2,000 per week.
Campus library atrium: 6,000 visitors per week; 3% of visitors buy; average sale $5 (single cups); rent $600 per week.

### You

Task 4: Pop-up location. Wildframe can run one four-week pop-up stand this spring, with a total rent budget of $5,000 for the four weeks. Use the location data in the system prompt to decide where it should go. Required format: the response must end with a single line that starts with Recommendation: followed by the location's name.

### Claude

# Pop-up location: where Wildframe should set up

Here's the weekly math for each spot (visitors × buy rate × average sale), then the four-week totals against the $5,000 rent budget.

| Location | Buyers/week | Revenue/week | Rent/week | Left after rent/week | 4-week rent | Fits $5,000? |
|---|---|---|---|---|---|---|
| Riverside Farmers Market | 180 | $2,520 | $900 | $1,620 | $3,600 | Yes |
| Union Station concourse | 150 | $900 | $2,000 | -$1,100 | $8,000 | No |
| Campus library atrium | 180 | $900 | $600 | $300 | $2,400 | Yes |

**Union Station is out.** It has the biggest crowd, but only 0.5% of people buy, and most of them grab a $6 cup. That's $900 a week in sales against $2,000 in rent, so we'd lose money every week. The four-week rent of $8,000 also blows past our $5,000 budget.

**The campus library is safe but small.** It has a great buy rate, but at $5 a cup we'd bring in $3,600 over four weeks and keep about $1,200 after rent. It's cheap to run, but it doesn't do much for us.

**Riverside is the clear winner.** It brings in about $10,080 over four weeks, and after $3,600 in rent we keep roughly $6,480, more than five times the library's take. It also fits the business:
- **Whole-bean bags are the main sale.** That's what we sell online and through subscriptions, so every bag is a chance to pitch the monthly plan.
- **The crowd matches our customers.** Farmers market regulars tend to care where their food and drink come from, which suits our environmentally minded urban professionals.
- **It leaves room in the budget.** We'd use $3,600 of the $5,000, so there's about $1,400 left for signage, samples, or a sign-up incentive.

One caveat: these figures are revenue, not profit. Beans, packaging, and staffing still come out of that. But Riverside's lead is big enough that those costs shouldn't change the answer.

Recommendation: Riverside Farmers Market

## Reflection

All four runs met their required formats, but the quality of the results differed more than the formatting did. The zero-shot perks in Task 1 followed the rules (six numbered ideas, one sentence each), but most of them, like a free mug or a members-only tasting, could have come from any subscription brand. The few-shot replies in Task 3 sounded much more like Wildframe: "Nobody should face a Thursday without beans" has the same dry humor as the example "Your beans will wait for you, mostly patiently." That makes the few-shot choice the one that made the biggest difference, since the examples showed Claude the brand voice instead of just describing it. Claude also added a note warning that Reply 2 assumes Wildframe sells decaf, which was useful even though it went beyond the required format.

The one-shot bean cards in Task 2 matched the house layout exactly. Still, Claude listed "low acidity" as a flavor under "Tastes like," and its "Real talk" lines ran two sentences when the example had one short line, so one example fixed the layout but not every detail.

The choice I'm least sure of is chain-of-thought for Task 4. My prompt never actually asked Claude to reason step by step; it worked through the math on its own. Its numbers checked out, but I can't tell whether the technique or the model deserves the credit. Next time, I would add an explicit instruction to calculate weekly revenue, profit after rent, and four-week rent for each location before recommending, then compare that run with this one.
