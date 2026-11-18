#include "machine_init_defs.h"

/* Same LED global IO enable as FG-4GT-2SX_V2.0, whose LED wiring is reused. */
void machine_custom_init(void) __banked
{
	REG_SET(RTL837X_REG_LED_GLB_IO_EN, 0x7624155b);
}
