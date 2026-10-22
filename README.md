# lvCompHelper

lvCompHelper is a low-complexity transpiler for use with National Instruments LabVIEW software. It is intended to be run inside of a calling block diagram and should yield platform-agnostic C code.

The transpiler's implementation is intended to be very readable, and makes use of Python's built-in AST library. As such, the syntax for input strings is built on Python operators.

In order to understand the usage of the transpiler, we must understand the application. This transpiler creates code that must be executed extremely quickly on a remote target. The software is written with a target of over 1kHz sampling, necessitating a <1ms execution time. Ideally, the on-target LabVIEW code does the following:


 > [Analog Read Nchan 1Samp](https://www.ni.com/docs/en-US/bundle/ni-daqmx-labview-api-ref/page/vi-lib/daqmx/read-llb/daqmx-read-analog-1d-dbl-nchan-1samp-vi.html) (get current data) -> Call `.so` compiled from the result of this transpiler (get the translations/output of the current data in a new array) -> [Analog Write Nchan 1Samp](https://www.ni.com/docs/en-US/bundle/ni-daqmx-labview-api-ref/page/vi-lib/daqmx/write-llb/daqmx-write-analog-1d-dbl-nchan-1samp-vi.html) (write the new array as needed) -> Enqueue current data and new array to stream values.

The transpiler function is `generate_c_library`, with the signature:
```python
def generate_c_library(
    phys_channels: list[str], 
    virt_labels: list[str], 
    virt_formulas: list[str]
) -> tuple[str, int]:
```

 - `phys_channels` represents a list of user-defined labels for each of the input values.
 - `virt_labels` represents a list of user-defined labels for each of the output values.
 - `virt_formulas` represents a list of user-defined functions in Python syntax to evaluate for each of the output values.

The return is a tuple of a `str` containing the generated code and an `int` containing a count of transient registers to reserve. The string is intended to be sent to and compiled on the remote target during a setup phase, where the resulting `.so` will be called.

For information on usage, see [ref.md](/ref.md). For a demonstration of the main function, see [main.py](/src/main.py) and subsequently the generated code in [main.c](/src/main.c).