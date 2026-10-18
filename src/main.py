
from lvchAST import generate_c_library
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    
    # Code reference from ref.md
    print(generate_c_library(
        phys_channels = ["T_amb", "T_surf", "T_fluid"], 
        virt_labels = ["T_mean", "T_max"], 
        virt_formulas = ["(T_amb + T_surf + T_fluid) / 3",
            "T_surf if T_surf >= T_fluid else T_fluid"]
    ))