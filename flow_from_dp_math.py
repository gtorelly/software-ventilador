"""
Analysis of the expected pressure difference for a given orifice tube 
diameter and flow rate
"""

import numpy as np

def dp_from_flow():
    """
    Calculates the differential based on the flow
    """
    pass

def flow_from_dp_schena():
    """
    Calculates the flow from a differential pressure based on the work by Schema et al. (2013, 
    10.1016/j.flowmeasinst.2013.09.001).
    """

def flow_from_dp_compressible(P_1, P_2, D_1, D_2, rho_1)
    """
    Calculates the flow of a compressible fluid. Depends on the absolute pressure (P_1 and P_2, in
    Pa) and density of the fluid. Also needs the dimensions of the tube (D_1, in m) and orifice 
    (D_2, in m), and the air density upstream (rho_1, in kg/m³).
    The formula was obtained from wikipedia's Orifice Plate entry, and the source is ISO5167-1:2003.
    https://en.wikipedia.org/wiki/Orifice_plate
    q_v is the volumetric air flow in m³/s = 60000 l/min
    """  
    C_d = 0.6  # Coefficient of discharge
    gamma = 1.4  # Heat capacity ratio
    beta = D_2 / D_1  # diameter ratio of orifice diameter D_2 to pipe diameter D_1

    # The equation depends on whether the flow is choked or not, therefore it is necessary to check
    choked_flow = False
    if beta < 0.25:  # Compressible flow
        choked_flow = True

    C = C_d / (1.0 - beta ** 4.0) ** 0.5  # Orifice flow coefficient
    A_2 = np.pi * (D_2 / 2.0) ** 2  # Area of the orifice
    
    if choked_flow:
        q_v = C * A_2 * (gamma * (P_1 / rho_1) * (2 / (gamma + 1))
                         ** ((gamma + 1) / (gamma - 1))) ** 0.5
    else
        q_v = C * A_2 * ((2 * (P_1 / rho_1) * (gamma / (gamma - 1))
                          * ((P_2 / P_1) ** (2 / gamma) - (P_2 / P_1) ** ((gamma + 1) / gamma))) 
    return q_v

def flow_from_dp_incompressible(delta_p, D_1, D_2, rho):
    """
    Calculates the flow for a given differential pressure (delta_p, in Pa). Also needs the 
    dimensions of the tube (D_1, in m) and orifice (D_2, in m) and the air density (rho, in kg/m³).
    The formula was obtained from wikipedia's Orifice Plate entry, and the source is ISO5167-1:2003.
    https://en.wikipedia.org/wiki/Orifice_plate
    q_v is the volumetric air flow in m³/s = 60000 l/min
    """

    C_d = 0.6  # Coefficient of discharge
    gamma = 1.4  # Heat capacity ratio
    beta = D_2 / D_1  # diameter ratio of orifice diameter D_2 to pipe diameter D_1


    q_v = ((C_d / (1.0 - beta ** 4.0) ** 0.5) * (np.pi / 4.0) * D_2 ** 2.0
           * (2.0 * delta_p * rho) ** 0.5)

    # Converting from m³/s to l/minute
    flow = q * 60000 * flow_dir
    return flow  # flow in liters per minute

if __name__ == __main__:
    print("Main")