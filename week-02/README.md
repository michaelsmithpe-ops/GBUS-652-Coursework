# Week 02

Materials and coursework for Week 2 of GBUS 652: AI & LLM Foundations.

## Prompt Lab

[`prompt-lab.html`](prompt-lab.html) is a single-file web app for testing prompts against Claude (`claude-sonnet-5-5`) through the Anthropic API, built with Claude Code using plain HTML, CSS, and JavaScript (no server, no dependencies). 

**▶ [Try it online](https://michaelsmithpe-ops.github.io/GBUS-652-Coursework/week-02/prompt-lab.html)**, or download the file and open it in any modern browser.

- **API key:** paste your Anthropic API key into the password field each time you open the page. The key is kept in memory only and is never saved or written to any file.
- **System prompt (optional):** stays in its box after you send. Changing it mid-conversation is noted in the log.
- **Conversation log:** every message is labeled *System*, *You*, or *Claude*. Each prompt is sent along with the whole conversation so far, and the log shows what was sent with it.
- **New Conversation** clears the log and starts fresh. **Export** downloads the conversation as a Markdown file.
- Replies are shown as plain text with line breaks kept. A waiting indicator appears while Claude responds, and any errors show up in the log.

### Sample export

[`prompt-lab-2026-10-27-1147.md`](prompt-lab-2026-10-27-1147.md) is a three-turn test conversation exported from Prompt Lab. The last turn ("What did I just ask you to do?") shows that each prompt is sent with the conversation so far, so Claude can recall earlier messages.
