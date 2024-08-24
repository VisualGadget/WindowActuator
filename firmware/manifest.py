freeze("$(PORT_DIR)/modules")
include("$(MPY_DIR)/extmod/asyncio")
require("umqtt.simple")

package("microdot", base_path="../ext_modules/microdot/src/microdot")
package("utemplate", base_path="../ext_modules/utemplate")
