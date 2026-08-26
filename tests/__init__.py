"""ToolTrace Bench test suite.

Making ``tests`` a regular package guarantees that ``from tests.conftest
import ...`` always resolves to *this* repository's conftest, even when a
foreign ``tests`` namespace package (e.g. another project's checkout) happens
to appear earlier on ``sys.path``. Regular packages take precedence over
namespace portions during import scanning.
"""
