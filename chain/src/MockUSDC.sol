// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

/// @title MockUSDC
/// @notice A 6-decimal ERC-20 test stand-in for USDC. It is not USDC and has no value.
///         It deploys only on the test chains DekernAI allows: anvil (31337), Base Sepolia (84532)
///         and Ethereum Sepolia (11155111) (decision D-33). Any other chain, mainnets included,
///         reverts in the constructor. Only the deployer can mint, so on a public test network
///         nobody else can create balances in it.
contract MockUSDC {
    string public constant name = "DekernAI Demo USD (test stand-in, not USDC)";
    string public constant symbol = "tUSDC";
    uint8 public constant decimals = 6;

    address public immutable minter;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor() {
        require(
            block.chainid == 31337 || block.chainid == 84532 || block.chainid == 11155111,
            "MockUSDC: test chains only"
        );
        minter = msg.sender;
    }

    function mint(address to, uint256 amount) external {
        require(msg.sender == minter, "MockUSDC: minter only");
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= amount, "MockUSDC: allowance");
        if (allowed != type(uint256).max) {
            allowance[from][msg.sender] = allowed - amount;
        }
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(to != address(0), "MockUSDC: zero address");
        require(balanceOf[from] >= amount, "MockUSDC: balance");
        unchecked {
            balanceOf[from] -= amount;
        }
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }
}
