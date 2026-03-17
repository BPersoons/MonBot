"""
Test Runner - Run All ADK Tests
Executes integration and scenario tests with reporting.
"""

import subprocess
import sys
from pathlib import Path


def run_tests():
    """Run all ADK integration tests."""
    print("="*80)
    print(" ADK INTEGRATION TEST SUITE")
    print("="*80)
    
    # Change to project directory
    project_root = Path(__file__).parent.parent
    
    # Test commands
    test_commands = [
        {
            'name': 'Integration Tests',
            'cmd': ['pytest', 'tests/test_integration.py', '-v', '--tb=short'],
            'description': 'Tests agent communication and StateStore integration'
        },
        {
            'name': 'Scenario Tests',
            'cmd': ['pytest', 'tests/test_scenarios.py', '-v', '--tb=short'],
            'description': 'Tests realistic trading scenarios'
        },
        {
            'name': 'End-to-End Test',
            'cmd': ['python', 'tests/test_adk_e2e.py'],
            'description': 'Tests complete trading cycle'
        }
    ]
    
    results = []
    
    for test in test_commands:
        print(f"\n{'='*80}")
        print(f" {test['name']}")
        print(f" {test['description']}")
        print(f"{'='*80}\n")
        
        try:
            result = subprocess.run(
                test['cmd'],
                cwd=project_root,
                capture_output=False,
                text=True
            )
            
            success = result.returncode == 0
            results.append((test['name'], success))
            
            if success:
                print(f"\n✅ {test['name']} PASSED")
            else:
                print(f"\n❌ {test['name']} FAILED")
                
        except Exception as e:
            print(f"\n❌ Error running {test['name']}: {e}")
            results.append((test['name'], False))
    
    # Summary
    print("\n" + "="*80)
    print(" TEST SUMMARY")
    print("="*80)
    
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{name:.<50}{status}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    print(f"\nTotal: {passed}/{total} passed ({passed/total*100:.0f}%)")
    print("="*80)
    
    return all(success for _, success in results)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
