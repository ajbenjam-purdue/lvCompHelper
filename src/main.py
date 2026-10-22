
from lvchAST import generate_c_library
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    
    # Code reference from ref.md
    code, registers = generate_c_library(
        phys_channels = ["T_amb", "T_surf", "T_fluid"], 
        virt_labels = ["T_mean", "T_max", "Test"], 
        virt_formulas = ["(T_amb + T_surf + T_fluid) / 3",
            "T_surf if T_surf >= T_fluid else T_fluid",
            "PID(T_amb, T_mean, 3, 4, 5) - PID(T_amb, T_mean, 0, 1, 2)"]
    )
    print(code)