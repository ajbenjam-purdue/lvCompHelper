
from lvchAST import generate_c_library, get_functions
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    # Display avail functions
    print(*get_functions(), sep="\n")
    
    # Code reference from ref.md
    code = generate_c_library(
        phys_channels = ["phys_0"], 
        virt_labels = [
            "test_math_0", 
            "test_math_1", 
            "test_math_2", 
            "test_pid", 
            "test_pida", 
            "test_ema", 
            "test_elapsed", 
            "test_time_delta", 
            "test_slew_limit",
            "test_delta"
        ], 
        virt_formulas = [
            "log10(abs(phys_0)+1.0) ** 2",
            "round(0.51) + floor(1.1)",
            "fmin(fmax(-1.0, 2.0), 1.0)",
            "PID(phys_0, 10, 0.25, 0.1, 0.05)",
            "PIDa(phys_0, 10, 0.25, 0.1, 0.05, 1, -1, 5)",
            "EMA(test_pid, 0.75)",
            "elapsed()",
            "time_delta()",
            "slew_limit(test_pid, 0.2)",
            "delta(test_pid)"
        ]
    )
    
    try:
        import pyperclip
        pyperclip.copy(code)
        print("Code copied to clipboard") # none of that manual copy paste hogwash
    except:
        print(code) # we tried