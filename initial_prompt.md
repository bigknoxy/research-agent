You are an expert AI principal engineer and researcher specializing in agentic workflows, automated prompt optimization, and formal evaluation frameworks.

Your ultimate goal is to design and implement a single, production-grade, executable Python script for a terminal-native 'Deep Research Agent' CLI tool. However, you are strictly forbidden from considering this task complete until you have built a built-in Anthropic-inspired evaluation suite, successfully dogfooded the agent on a real task, and used a GEPA self-improvement loop to iteratively refactor the codebase to perfection.

### PART 1: THE CORE AGENT ARCHITECTURE
The CLI tool must feature fully implemented, non-placeholder modules utilizing explicit type hinting and robust error logging for:
1. Dynamic Task Decomposition (The Planner)
2. Resilient Web Crawler & Scraper (Stripping boilerplate HTML)
3. Contradiction & Divergence Engine (Flagging conflicting statistics/sources)
4. Context-Aware Synthesizer (Generating a structured Markdown report)
5. JSON Stateful Session Recovery (`research_state.json`)

### PART 2: THE ANTHROPIC EVALUATION HARNESS
Integrate a formal test suite modeled strictly on Anthropic's "Demystifying Evals for AI Agents" framework. The harness must decouple and log:
1. Task Definitions: Pre-seed a bank of 3 highly ambiguous, open-ended research topics containing baseline edge cases.
2. Execution Runs & Transcripts: The tool must programmatically trigger multi-run agent loops (measuring pass@k metrics). It must capture the full environmental execution trace—not just final text, but tool-call histories, token consumption, error rates, and reasoning paths.
3. Hybrid Graders: Implement a tiered grading block:
   - Code-based Graders: Deterministic execution assertions (file generation checks, regex string matches).
   - Model-based Graders: An internal LLM-as-a-judge rubric that scores the transcript for synthesis nuance and tool-use precision.

### PART 3: THE GEPA SELF-IMPROVEMENT LOOP
To drive continuous refinement, implement a self-contained Genetic-Pareto (GEPA) optimization pipeline within the code:
1. Candidate Pool Management: Track variants ("candidates") of the internal agent prompts and prompt layouts.
2. Natural Language Reflection: Instead of utilizing numeric scalar rewards, feed the captured Anthropic failure transcripts and error traces into a "Reflector" routine. Have it diagnose why a candidate run failed or hallucinated.
3. Mutation & Pareto Selection: Generate prompt mutations or cross-over lessons based on those text-reflections. Filter the top performers along a Pareto Frontier balancing accuracy, token consumption, and tool execution speed.

### EXECUTION COMMAND
Before outputting code, engage your interleaved thinking capabilities to plan this unified, self-evolving system architecture.

Once your thinking is complete, output the full Python script containing the Agent, the Evals, and the GEPA loop. Finally, append an 'Autonomic Execution Block' inside a `if __name__ == '__main__':` block. When run, this script must immediately dogfood itself: running the evaluation suite, executing the GEPA self-improvement generations over the pool, and overwriting or outputting an optimized, fully vetted revision of itself. Do not stop until the tool has proved its own reliability.
