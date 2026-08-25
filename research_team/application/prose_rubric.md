<!--
Two readers, two halves. Everything above the separator states what good prose
is; it is the `lesson-drafter`'s brief and the `prose-critic`'s standard, and it
reads correctly to a writer and to a judge alike. Everything below the separator
is the critic's reporting contract, and is addressed to the critic alone.

The split exists because the tail, handed to a drafter, tells it to judge the
lesson, to report nothing else, and not to rewrite it -- three instructions that
fight the one instruction a drafter has, and an OUTPUT contract that competes
with the real one further down its prompt. The likely result is a critique
where a lesson should be.

This comment is for whoever edits the file. `prose_rubric.py` strips it from
both halves, because a subagent handed the file's maintenance notes has been
handed instructions that are not about its job.
-->

Six rules. Each is pass or fail. There is no score: a five-point scale asks for
a judgement nobody can defend and gets a 4 for everything.

1. **Opens with a problem, not a thesis.** The first 80 words carry a specific
   moment: a failure, a measured number that surprised somebody, or two
   plausible answers that disagree. The concept is named after it, not before.
   "A system that records what happens has a choice about where to record it"
   fails: it is a topic sentence, nothing is at risk, and there is no reason to
   read the second sentence.

2. **Something is withheld.** At least one question is raised and left open for
   a paragraph or more before it is answered. A lesson that answers each
   question in the sentence that asks it leaves the reader holding nothing.

3. **One stated cost.** The lesson says what breaks if the learner gets this
   wrong, with evidence from the corpus. "A leak in one does not expose the
   other" fails: it is abstract, and the lesson never shows the leak.

4. **At most one unpacking, and the format does not matter.** Unpacking is
   the move where a lesson presents something -- a block quote, an inline
   quotation, a paraphrase, or its own claim -- and then walks the reader back
   through its parts: announcing how many parts it has, naming each, restating
   each in the lesson's own words. Count the move, not the format. The same
   move on an inline quotation is the same failure as on a block quote, and a
   lesson holding one block quote can still perform it twice. The tell is a
   sentence whose only work is to tell the reader that the previous sentence
   has parts. Twice or more, the reader learns every citation arrives with its
   own explanation and stops reading the citations.

5. **Second person with a task.** The reader is doing something. "A learner who
   understands them can answer..." fails; "You are about to add an event.
   Which file does it go in?" passes.

6. **Varied section shape.** No two consecutive sections are built the same
   way. Parallel lists of bolded nouns only where the parallelism is
   load-bearing, never as decoration.

--- CRITIC ONLY: how to report a failure, not what counts as one ---

Judge only the six rules above, and cite the number of every rule the lesson
fails.

Report each failure as the rule number, the sentence or passage that fails it,
and one line saying why. Report nothing else. Do not rewrite the lesson, do not
praise what worked, and do not suggest wording -- the drafter holds the plan
slot and the material, and will revise better than you can from outside it.

If a lesson passes all six, say so in one line.
