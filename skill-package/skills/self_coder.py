import os
import re
import random
import logging

logger = logging.getLogger(__name__)

async def mutate_strategy(agent_id, penalty_tags):
    """
    Reads the agent's strategy.py and 'evolves' it by disabling 
    logic related to the penalized tags.
    
    Args:
        agent_id (str): The ID of the agent (to find the file).
        penalty_tags (list): List of tags to penalize (e.g. ['RANDOM_TEST']).
        
    Returns:
        bool: True if mutation was successful.
    """
    try:
        # 1. Locate the strategy file
        # Check specific agent data dir first
        strategy_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "agents", agent_id, "strategy.py")
        strategy_path = os.path.abspath(strategy_path)
        
        if not os.path.exists(strategy_path):
            logger.error(f"❌ Strategy file not found at {strategy_path}")
            return False

        # 2. Read current code
        with open(strategy_path, 'r') as f:
            code = f.read()
        
        original_code = code
        mutation_log = []

        # 3. Apply mutations based on penalties
        for tag in penalty_tags:
            logger.info(f"🧬 Evolving to fix penalty: {tag}")
            
            if tag == "RANDOM_TEST":
                # Specific logic to disable the random test block
                # We look for the block and comment it out or change the condition
                
                # Pattern: Find the block where RANDOM_TEST is used/appended
                # Case A: "reason = ['RANDOM_TEST']"
                pattern_a = r"(reason\s*=\s*\[.*'RANDOM_TEST'.*\])"
                if re.search(pattern_a, code):
                    code = re.sub(pattern_a, r"# \1 # DISABLED BY EVOLUTION", code)
                    mutation_log.append(f"Disabled logic block for {tag}")

                # Case B: "if ... : # RANDOM_TEST logic"
                # This is a bit harder with regex, so we'll look for specific keywords associated with the bad logic
                # For the template strategy, we know it uses "random.random() < 0.1" for this test.
                pattern_b = r"(if\s+random\.random\(\)\s*<\s*0\.1\s*:)"
                if re.search(pattern_b, code):
                    code = re.sub(pattern_b, r"if False: # EVOLVED: Removed random noise", code)
                    mutation_log.append(f"Hard-disabled random trigger for {tag}")

            elif tag == "MOMENTUM_UP":
                # Example: Tighten the threshold
                # "momentum > 0.02" -> "momentum > 0.04"
                pass # TODO: Implement more complex parameter tuning

        # 4. Save if changed
        if code != original_code:
            # Add evolution header
            header_pattern = r"# Darwin SDK - .* Strategy"
            new_header = f"# Darwin SDK - {agent_id} Strategy (Evolved v{random.randint(10,99)})"
            if re.search(header_pattern, code):
                code = re.sub(header_pattern, new_header, code)
            else:
                code = new_header + "\n" + code

            with open(strategy_path, 'w') as f:
                f.write(code)
            
            logger.info(f"✅ Strategy mutated successfully! Changes: {mutation_log}")
            return True
        else:
            logger.info("⚠️ No matching logic found to mutate.")
            return False

    except Exception as e:
        logger.error(f"❌ Mutation failed: {e}")
        return False
