## What I Built
My tool, `week-03/ask.py`, is a command-line RAG tool. It splits every document in a folder into one chunk per section, stores the chunks in a local Chroma database using Chroma's built-in embedding model, retrieves the 4 most similar chunks for each question, and sends them to Claude (`claude-sonnet-5`) with instructions to answer only from those sources, cite the source file for every fact, and say so when the sources don't contain the answer. To make it work with Larkfield's documents, I added a `--docs` option that names the document folder (Copperline stays the default), gave each folder its own Chroma database under `week-03/chroma_db/`, removed the Copperline-specific wording from the system prompt, and added a `--save` option that writes each run (question, retrieved chunks, then the answer) to a numbered, timestamped file in `week-03/saved-answers/`. I made seven runs: Question 1 before and after fixing a problem in the document collection, then Questions 2 through 6.

## Why This Approach
Chunking method: structure
Makes sense on its own: Yes, because every chunk starts with its document title, section heading, and version line, so for example "Consumer Fee Schedule - Wire transfers" makes clear what its list of $10 to $45 fees refers to.
Label and source: Both, because each stored chunk begins with a line like "Consumer Fee Schedule - Wire transfers" followed by "Source: consumer-fee-schedule.html", and the source file is also saved as metadata that the tool prints for every retrieved chunk.
Short enough: Yes, because I measured all 30 Larkfield chunks including their title and source header, and they range from 42 to 128 words, with the longest (Overdraft and returned item fees) still well under about 190 words.

## Example Run
```
QUESTION
Question 4: Can I refund the outgoing international wire transfer fee for a member without approval from a manager?

Top 4 retrieved chunks:
  #1  similarity 0.630  consumer-fee-schedule.html
      Section: Wire transfers
      - Incoming domestic wire transfer: $10. - Incoming international wire transfer: $15. - Outgoing domestic wire transfer: $25. - Outgoing international ...
  #2  similarity 0.575  fee-refund-guide.html
      Section: Refunds that need a branch manager
      A refund needs the branch manager's approval when the fee is more than $30, when the member has already had a refund in the last 90 days, or when the ...
  #3  similarity 0.536  fee-refund-guide.html
      Section: What a member service representative can approve
      A member service representative may approve a refund of a single fee of $30 or less without anyone else's approval. A representative may approve only ...
  #4  similarity 0.497  fee-refund-guide.html
      Section: Refunds that need the Member Services Director
      Refunds of more than $150 in total for one member in any 90-day period need the Member Services Director's approval. So does any refund for a business...

ANSWER
No. The outgoing international wire transfer fee is $45 [consumer-fee-schedule.html]. A member service representative can only approve refunds of a single fee of $30 or less without further approval [fee-refund-guide.html]. Since $45 exceeds that threshold, the refund needs branch manager approval [fee-refund-guide.html].

Additional conditions that could change the required approval level:
- If the member has already had a refund in the last 90 days, or is asking for several fees to be refunded at once, branch manager approval is also required (which it already is here) [fee-refund-guide.html].
- If the total refunds for that member in a 90-day period exceed $150, or if the account is a business account, approval from the Member Services Director is needed instead of the branch manager [fee-refund-guide.html].
```

## Reflection
What was wrong: The problem was consumer-fee-schedule-v7.html, an outdated Version 7 fee schedule still labeled "current"; for Question 1 the retrieved chunks included the same Overdraft section from both Version 8 ($29 per item) and Version 7 ($35 per item), and Version 7 copies filled 2 of the 4 retrieval slots.
How I fixed it: Moved consumer-fee-schedule-v7.html out of week-03/larkfield-docs into week-03/larkfield-docs-archive so the tool no longer reads it, then rebuilt the database, which went from 39 chunks in 6 documents to 30 chunks in 5 documents.
Prevention: Archive process, meaning that whenever Larkfield publishes a new version of a document, its owner moves the old version to an archive and relabels it as superseded on the same day, so only one current version is ever in the collection.
Question 6: Declined, because retrieval returned only unrelated chunks about stop payments, certificate dividend rates, checking fees, and wire fees, all with very low similarity scores between 0.20 and 0.27.
