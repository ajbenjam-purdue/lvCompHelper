
from lvchAST import generate_c_library
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    
    # Test code with imaginative naming
    physical = ["ch_0", "ch_1", "ch_2", "ch_3", "ch_4"]
    
    # Assuming no loops, order is not relevant
    virtual = {
        "vch_0" : "ch_0 + 5",
        "vch_1" : "(vch2 - 2.5) ** 2",
        "vch_2" : "ch_1 + ch_2 + ch_3 + ch_4",
        "vch_3" : "sin(vch_2 - vch_1)"
    }
    
    virtual_names = list(virtual.keys())
    virtual_formulae = list(virtual.values())

    print(generate_c_library(physical, virtual_names, virtual_formulae))