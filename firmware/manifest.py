freeze("$(PORT_DIR)/modules")
include("$(MPY_DIR)/extmod/asyncio")


package("wa", base_path="../freeze")
package("templates", base_path="../freeze")
module("boot.py", base_path="../freeze")
module("main.py", base_path="../freeze")
