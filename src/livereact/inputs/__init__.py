"""Input sources behind one interface: DemoDataSource (Phase 1) and the real
Pro DJ Link + MIDI listeners (Phase 7). All push immutable messages onto a queue;
none mutate ShowState directly. (Analysis: docs/05 §4.3.)"""
