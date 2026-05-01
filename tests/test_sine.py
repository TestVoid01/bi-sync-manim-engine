import sys
try:
    import manim
    from manim import Axes, BLUE, PI, config
    import numpy as np

    config.renderer = "opengl"
    
    axes = Axes(x_range=[-4, 4, 1], y_range=[-3, 3, 1])
    sine = axes.plot(lambda x: np.sin(x), x_range=[-4, 4], color=BLUE)

    print("Type:", type(sine).__name__)
    print("MRO:", [c.__name__ for c in type(sine).__mro__])
    print("Has points:", hasattr(sine, 'points'))
    if hasattr(sine, 'points'):
        print("Points shape:", np.array(sine.points).shape)
        print("Num NaNs:", np.sum(np.isnan(sine.points)))
    print("Has get_shader_wrapper_list:", hasattr(sine, 'get_shader_wrapper_list'))
    if hasattr(sine, 'get_shader_wrapper_list'):
        wrappers = sine.get_shader_wrapper_list()
        print("Shader wrappers count:", len(wrappers))
        if wrappers:
            print("Wrapper 0 program:", wrappers[0].program_id if hasattr(wrappers[0], 'program_id') else "No program_id")

except ImportError as e:
    print("Manim not found in this python env:", sys.executable)
