/* SPDX-License-Identifier: Apache-2.0 */
ENTRY(_start)
PHDRS { payload PT_LOAD FLAGS(5); }
SECTIONS
{
    . = 0x00200000;
    .text : { *(.text*) *(.rodata*) } :payload
    /DISCARD/ : { *(.note*) *(.comment*) }
}
