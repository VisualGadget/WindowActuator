freeze("$(PORT_DIR)/modules")
include("$(MPY_DIR)/extmod/asyncio")
require("umqtt.simple")

package("utemplate", base_path="../ext_modules/utemplate")
package("microdot", base_path="../ext_modules/microdot/src")

package("wa", base_path="../freeze")
module("boot.py", base_path="../freeze")
module("main.py", base_path="../freeze")
