"""Show engines (Phases 3-6): ReactiveLayer, PhraseEngine, TransitionEngine.
Engines never call each other; they read a ShowState snapshot and write additively
to a scene buffer. (Analysis: docs/02 FR-2.4, docs/05 §5.3.)"""
